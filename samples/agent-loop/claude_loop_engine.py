# Excerpt from claude_loop_engine.py (1,405 lines total)
# Full source implements 7-step INSPECT→PLAN→VALIDATE→EXECUTE→VERIFY→LOG→DECIDE protocol

#!/usr/bin/env python3
"""
Claude Loop Engine - The BRAIN of autonomous bug bounty hunting.

Implements the 7-step protocol:
INSPECT → PLAN → VALIDATE → EXECUTE → VERIFY → LOG → DECIDE

This engine:
1. Captures page state including screenshots
2. Sends state to Claude for analysis (multimodal)
3. Validates Claude's proposed action for safety
4. Executes the action via ToolAPI
5. Verifies the result
6. Logs everything
7. Decides next action based on results

Claude is IN THE LOOP at every step - analyzing visuals, making decisions,
and adapting strategy based on what it observes.
"""

import asyncio
import json
import os
import base64
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging
import re

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from .tool_api import ToolAPI, Finding, BrowserState, Screenshot, Severity, Evidence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LAB_DIR = Path("/home/hercules/h1-security-lab")
OUTPUT_DIR = LAB_DIR / "output"


class DebugMode(Enum):
    """Debug verbosity levels."""
    OFF = "off"            # Normal operation, no debug overhead
    OBSERVE = "observe"    # Watch only: save every state, full reasoning visible
    STEP = "step"          # Step-through: pause after each iteration for operator input
    BREAKPOINT = "breakpoint"  # Run freely, pause only on breakpoint conditions


@dataclass
class Breakpoint:
    """Condition that pauses execution in BREAKPOINT debug mode."""
    name: str
    condition_type: str   # "finding", "severity", "url", "iteration", "action", "risk"
    value: str            # Pattern or threshold to match
    enabled: bool = True
    hit_count: int = 0

    def matches(self, state: 'HuntState', action: 'Action', iteration: int) -> bool:
        """Check if breakpoint condition is met."""
        if not self.enabled:
            return False
        if self.condition_type == "finding":
            return action.type == ActionType.VULNERABILITY_FOUND
        if self.condition_type == "severity":
            return (action.type == ActionType.VULNERABILITY_FOUND and
                    action.extra_data.get("severity", "").lower() == self.value.lower())
        if self.condition_type == "url":
            return self.value.lower() in state.url.lower()
        if self.condition_type == "iteration":
            return iteration >= int(self.value)
        if self.condition_type == "action":
            return action.type.value == self.value
        if self.condition_type == "risk":
            return action.risk_level.value == self.value
        return False


class DebugController:
    """
    Operator debug interface for the Claude Loop Engine.

    Provides step-through, breakpoints, goal override, and full
    iteration inspection without requiring a separate UI.

    Modes:
        OFF        - No debug overhead, normal execution
        OBSERVE    - Saves detailed per-iteration snapshots to debug/ dir
        STEP       - Pauses after every iteration for operator command
        BREAKPOINT - Runs freely, pauses only when a breakpoint triggers

    Operator commands at pause:
        c / continue   - Resume execution
        s / step       - Execute one iteration, then pause again
        g <new goal>   - Override the current hunt goal
        f <vuln_focus> - Change vulnerability focus (idor, xss, ssrf...)
        r <level>      - Change risk tolerance (low, medium, high, critical)
        b <type> <val> - Add breakpoint (e.g. b severity high)
        bl             - List breakpoints
        bd <name>      - Disable breakpoint
        i              - Show full iteration state (last captured)
        h              - Show findings so far
        q / quit       - Abort the hunt gracefully
    """

    def __init__(self, mode: DebugMode = DebugMode.OFF, output_dir: Path = None):
        self.mode = mode
        self.output_dir = output_dir
        self.debug_dir = None
        self.breakpoints: List[Breakpoint] = []
        self._step_once = False  # For "step" command in BREAKPOINT mode
        self._last_state: Optional['HuntState'] = None
        self._last_action: Optional['Action'] = None
        self._goal_override: Optional[str] = None
        self._focus_override: Optional[str] = None
        self._risk_override: Optional[str] = None
        self._abort = False

        if mode != DebugMode.OFF and output_dir:
            self.debug_dir = output_dir / "debug"
            self.debug_dir.mkdir(parents=True, exist_ok=True)

    @property
    def active(self) -> bool:
        return self.mode != DebugMode.OFF

    def save_iteration_snapshot(
        self, iteration: int, state: 'HuntState', action: 'Action',
        result: Optional['ActionResult'], status: str
    ):
        """Save detailed iteration snapshot to debug directory."""
        if not self.debug_dir:
            return

        snapshot = {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "url": state.url,
            "title": state.title,
            "forms_count": len(state.forms),
            "elements_count": len(state.interactive_elements),
            "network_requests_count": len(state.network_requests),
            "action": {
                "type": action.type.value,
                "target": action.target,
                "value": action.value,
                "reasoning": action.reasoning,
                "risk": action.risk_level.value,
                "requires_checkpoint": action.requires_checkpoint,
                "extra_data": action.extra_data
            },
            "result": {
                "success": result.success if result else None,
                "message": result.message if result else None,
                "has_finding": result.finding is not None if result else False
            } if result else None,
            "status": status
        }

        snapshot_file = self.debug_dir / f"iter_{iteration:03d}.json"
        with open(snapshot_file, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)

        # Save screenshot separately for easy viewing
        if state.screenshot_b64:
            ss_file = self.debug_dir / f"iter_{iteration:03d}.png"
            try:
                with open(ss_file, 'wb') as f:
                    f.write(base64.b64decode(state.screenshot_b64))
            except Exception:
                pass

    def should_pause(self, state: 'HuntState', action: 'Action', iteration: int) -> bool:
        """Determine if execution should pause for operator input."""
        if self._abort:
            return False
        if self.mode == DebugMode.STEP:
            return True
        if self.mode == DebugMode.BREAKPOINT:
            if self._step_once:
                self._step_once = False
                return True
            for bp in self.breakpoints:
                if bp.matches(state, action, iteration):
                    bp.hit_count += 1
                    print(f"\n  🔴 BREAKPOINT HIT: {bp.name} "
                          f"({bp.condition_type}={bp.value}, hits={bp.hit_count})")
                    return True
        return False

    def consume_overrides(self) -> dict:
        """Return and clear any pending overrides from operator commands."""
        overrides = {}
        if self._goal_override is not None:
            overrides["goal"] = self._goal_override
            self._goal_override = None
        if self._focus_override is not None:
            overrides["vuln_focus"] = self._focus_override
            self._focus_override = None
        if self._risk_override is not None:
            overrides["risk_tolerance"] = self._risk_override
            self._risk_override = None
        return overrides

    def pause_for_input(
        self, iteration: int, state: 'HuntState', action: 'Action',
        findings: List['Finding']
    ) -> str:
        """Pause and wait for operator command. Returns operator directive."""
        self._last_state = state
        self._last_action = action

        print(f"\n{'═' * 60}")
        print(f"  ⏸  DEBUG PAUSE — Iteration {iteration}")
        print(f"{'═' * 60}")
        print(f"  URL:       {state.url}")
        print(f"  Action:    {action.type.value} → {action.target or 'N/A'}")
        print(f"  Risk:      {action.risk_level.value}")
        print(f"  Reasoning: {action.reasoning[:80]}")
        print(f"  Findings:  {len(findings)}")
        print(f"{'─' * 60}")
        print("  Commands: [c]ontinue [s]tep [g]oal [f]ocus [r]isk "
              "[b]reakpoint [i]nspect [h]istory [q]uit")

        while True:
            try:
                cmd = input("  debug> ").strip()
            except (EOFError, KeyboardInterrupt):
                return "continue"

            if not cmd:
                continue

            parts = cmd.split(maxsplit=1)
            op = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if op in ("c", "continue"):
                if self.mode == DebugMode.STEP:
                    # In step mode, "continue" switches to run-until-breakpoint
                    self.mode = DebugMode.BREAKPOINT
                    print("  → Continuing (will pause at next breakpoint)")
                return "continue"

            elif op in ("s", "step"):
                if self.mode == DebugMode.BREAKPOINT:
                    self._step_once = True
                return "continue"

            elif op in ("g", "goal") and arg:
                self._goal_override = arg
                print(f"  → Goal override: {arg}")

            elif op in ("f", "focus") and arg:
                valid = ["idor", "xss", "ssrf", "sqli", "race", "graphql", "auth"]
                if arg.lower() in valid:
                    self._focus_override = arg.lower()
                    print(f"  → Focus override: {arg.lower()}")
                else:
                    print(f"  → Invalid focus. Options: {', '.join(valid)}")

            elif op in ("r", "risk") and arg:
                valid = ["low", "medium", "high", "critical"]
                if arg.lower() in valid:
                    self._risk_override = arg.lower()
                    print(f"  → Risk tolerance override: {arg.lower()}")
                else:
                    print(f"  → Invalid risk. Options: {', '.join(valid)}")

            elif op in ("b", "breakpoint"):
                if not arg:
                    print("  Usage: b <type> <value>")
                    print("  Types: finding, severity, url, iteration, action, risk")
                    print("  Example: b severity high")
                    continue
                bp_parts = arg.split(maxsplit=1)
                if len(bp_parts) < 2 and bp_parts[0] != "finding":
                    print("  Need type and value (except 'finding' which needs no value)")
                    continue
                bp_type = bp_parts[0]
                bp_val = bp_parts[1] if len(bp_parts) > 1 else ""
                bp_name = f"bp_{len(self.breakpoints)}"
                self.breakpoints.append(Breakpoint(bp_name, bp_type, bp_val))
                print(f"  → Breakpoint added: {bp_name} ({bp_type}={bp_val})")

            elif op == "bl":
                if not self.breakpoints:
                    print("  No breakpoints set")
                else:
                    for bp in self.breakpoints:
                        status = "ON" if bp.enabled else "OFF"
                        print(f"  [{status}] {bp.name}: {bp.condition_type}="
                              f"{bp.value} (hits: {bp.hit_count})")

            elif op == "bd" and arg:
                for bp in self.breakpoints:
                    if bp.name == arg:
                        bp.enabled = False
                        print(f"  → Disabled {bp.name}")
                        break
                else:
                    print(f"  → Breakpoint {arg} not found")

            elif op in ("i", "inspect"):
                if self._last_state:
                    s = self._last_state
                    print(f"\n  === FULL STATE ===")
                    print(f"  URL: {s.url}")
                    print(f"  Title: {s.title}")
                    print(f"  Forms: {len(s.forms)}")
                    for fi, form in enumerate(s.forms[:5]):
                        print(f"    [{fi}] action={form.get('action')} "
                              f"method={form.get('method')}")
                        for fld in form.get('fields', [])[:5]:
                            print(f"        {fld.get('name')} ({fld.get('type')})")
                    print(f"  Elements: {len(s.interactive_elements)}")
                    for ei, elem in enumerate(s.interactive_elements[:10]):
                        print(f"    [{ei}] <{elem.get('tag')}> "
                              f"{elem.get('text', '')[:40]} id={elem.get('id')}")
                    print(f"  Network: {len(s.network_requests)} requests")
                    for req in s.network_requests[-5:]:
                        print(f"    {req.get('method', 'GET')} {req.get('url', '')[:60]}")
                    print(f"  Cookies: {len(s.cookies)}")
                    print(f"  Errors: {s.errors}")
                    if s.screenshot_b64:
                        ss_path = self.debug_dir / "inspect_current.png" if self.debug_dir else None
                        if ss_path:
                            try:
                                with open(ss_path, 'wb') as f:
                                    f.write(base64.b64decode(s.screenshot_b64))
                                print(f"  Screenshot saved: {ss_path}")
                            except Exception:
                                pass
                    print(f"  === END STATE ===\n")

            elif op in ("h", "history"):
                if not findings:
                    print("  No findings yet")
                else:
                    for f in findings:
                        print(f"  [{f.severity.value.upper()}] {f.type} — {f.endpoint}")

            elif op in ("q", "quit"):
                self._abort = True
                return "abort"

            else:
                print("  Unknown command. Try: c, s, g <goal>, f <focus>, "
                      "r <risk>, b <type> <val>, bl, bd <name>, i, h, q")
