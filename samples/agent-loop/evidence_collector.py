#!/usr/bin/env python3
"""
Evidence Collector - Comprehensive evidence capture for H1 reports.

This module provides:
1. Multi-step screenshot capture
2. HTTP request/response logging
3. cURL command generation
4. PoC HTML generation
5. Video recording (optional)
6. Evidence packaging for reports

All evidence is organized per-finding and ready for H1 submission.
"""

import asyncio
import base64
import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import logging

from .tool_api import Finding, Screenshot, Evidence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ReproductionStep:
    """A single step in vulnerability reproduction."""
    step_number: int
    action: str
    description: str
    screenshot_path: Optional[str] = None
    request: Optional[Dict] = None
    response: Optional[Dict] = None
    expected_result: Optional[str] = None
    actual_result: Optional[str] = None


@dataclass
class EvidencePackage:
    """Complete evidence package for a finding."""
    finding_id: str
    finding_type: str
    severity: str
    target_url: str
    
    screenshots: List[str] = field(default_factory=list)
    reproduction_steps: List[ReproductionStep] = field(default_factory=list)
    http_requests: List[Dict] = field(default_factory=list)
    curl_commands: List[str] = field(default_factory=list)
    
    poc_html_path: Optional[str] = None
    poc_script_path: Optional[str] = None
    video_path: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    evidence_dir: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "reproduction_steps": [asdict(s) for s in self.reproduction_steps]
        }


class EvidenceCollector:
    """
    Collect and organize evidence for vulnerability reports.
    Generates H1-ready evidence packages.
    """
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.evidence_base = self.output_dir / "evidence"
        self.evidence_base.mkdir(parents=True, exist_ok=True)
    
    async def collect_for_finding(
        self,
        finding: Finding,
        browser=None,
        http_requests: List[Dict] = None
    ) -> EvidencePackage:
        """
        Collect comprehensive evidence for a finding.
        
        Args:
            finding: The Finding to collect evidence for
            browser: Optional BrowserIntegration instance for screenshots
            http_requests: List of HTTP requests/responses to include
        
        Returns:
            EvidencePackage with all collected evidence
        """
        evidence_dir = self.evidence_base / finding.id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        package = EvidencePackage(
            finding_id=finding.id,
            finding_type=finding.type,
            severity=finding.severity.value,
            target_url=finding.url,
            evidence_dir=str(evidence_dir)
        )
        
        if browser:
            screenshot_path = evidence_dir / "current_state.png"
            try:
                screenshot_b64 = await browser.screenshot()
                if screenshot_b64:
                    with open(screenshot_path, 'wb') as f:
                        f.write(base64.b64decode(screenshot_b64))
                    package.screenshots.append(str(screenshot_path))
            except Exception as e:
                logger.error(f"Failed to capture screenshot: {e}")
        
        if finding.screenshot_path and Path(finding.screenshot_path).exists():
            dest = evidence_dir / "finding_screenshot.png"
            shutil.copy(finding.screenshot_path, dest)
            package.screenshots.append(str(dest))
        
        if http_requests:
            package.http_requests = http_requests
            requests_file = evidence_dir / "requests.json"
            with open(requests_file, 'w') as f:
                json.dump(http_requests, f, indent=2)
        
        if finding.request:
            package.http_requests.append(finding.request)
        
        package.curl_commands = self._generate_curl_commands(package.http_requests)
        curl_script = evidence_dir / "reproduce.sh"
        with open(curl_script, 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("# Reproduction script for " + finding.id + "\n\n")
            for cmd in package.curl_commands:
                f.write(cmd + "\n\n")
        os.chmod(curl_script, 0o755)
        package.poc_script_path = str(curl_script)
        
        if finding.type.upper() in ["XSS", "CSRF", "CLICKJACKING", "OPEN_REDIRECT"]:
            poc_html = self._generate_poc_html(finding)
            poc_path = evidence_dir / "poc.html"
            with open(poc_path, 'w') as f:
                f.write(poc_html)
            package.poc_html_path = str(poc_path)
        
        for i, step in enumerate(finding.reproduction_steps):
            package.reproduction_steps.append(ReproductionStep(
                step_number=i + 1,
                action="manual",
                description=step
            ))
        
        manifest = evidence_dir / "manifest.json"
        with open(manifest, 'w') as f:
            json.dump(package.to_dict(), f, indent=2)
        
        logger.info(f"✅ Evidence collected for {finding.id}: {len(package.screenshots)} screenshots, {len(package.curl_commands)} curl commands")
        
        return package
    
    async def collect_step_by_step(
        self,
        finding: Finding,
        browser,
        steps: List[Dict]
    ) -> EvidencePackage:
        """
        Execute and capture reproduction steps with screenshots.
        
        Args:
            finding: The Finding to reproduce
            browser: BrowserIntegration instance
            steps: List of steps to execute, each with 'action', 'selector', 'value'
        
        Returns:
            EvidencePackage with step-by-step evidence
        """
        evidence_dir = self.evidence_base / finding.id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        package = EvidencePackage(
            finding_id=finding.id,
            finding_type=finding.type,
            severity=finding.severity.value,
            target_url=finding.url,
            evidence_dir=str(evidence_dir)
        )
        
        for i, step in enumerate(steps):
            step_num = i + 1
            action = step.get('action', 'unknown')
            
            before_path = evidence_dir / f"step_{step_num:02d}_before.png"
            before_b64 = await browser.screenshot()
            if before_b64:
                with open(before_path, 'wb') as f:
                    f.write(base64.b64decode(before_b64))
                package.screenshots.append(str(before_path))
            
            try:
                if action == 'navigate':
                    await browser.navigate(step['url'])
                elif action == 'click':
                    await browser.click(step['selector'])
                elif action == 'fill':
                    await browser.fill(step['selector'], step['value'])
                elif action == 'type':
                    await browser.type_text(step['selector'], step['value'])
                elif action == 'press':
                    await browser.press(step['key'])
                elif action == 'wait':
                    await asyncio.sleep(step.get('seconds', 1))
                elif action == 'execute_js':
                    await browser.execute_js(step['script'])
                
                success = True
                result = f"Completed: {action}"
            except Exception as e:
                success = False
                result = f"Failed: {e}"
            
            await asyncio.sleep(0.5)
            
            after_path = evidence_dir / f"step_{step_num:02d}_after.png"
            after_b64 = await browser.screenshot()
            if after_b64:
                with open(after_path, 'wb') as f:
                    f.write(base64.b64decode(after_b64))
                package.screenshots.append(str(after_path))
            
            package.reproduction_steps.append(ReproductionStep(
                step_number=step_num,
                action=action,
                description=step.get('description', f"{action} on {step.get('selector', step.get('url', 'target'))}"),
                screenshot_path=str(after_path),
                expected_result=step.get('expected'),
                actual_result=result
            ))
        
        manifest = evidence_dir / "manifest.json"
        with open(manifest, 'w') as f:
            json.dump(package.to_dict(), f, indent=2)
        
        return package
    
    def _generate_curl_commands(self, requests: List[Dict]) -> List[str]:
        """Generate cURL commands from HTTP requests."""
        commands = []
        
        for req in requests:
            url = req.get('url', '')
            method = req.get('method', 'GET')
            headers = req.get('headers', {})
            body = req.get('body') or req.get('post_data', '')
            
            cmd = f"curl -X {method}"
            
            for key, value in headers.items():
                value_escaped = value.replace("'", "'\\''")
                cmd += f" \\\n  -H '{key}: {value_escaped}'"
            
            if body:
                body_escaped = body.replace("'", "'\\''") if isinstance(body, str) else json.dumps(body).replace("'", "'\\''")
                cmd += f" \\\n  -d '{body_escaped}'"
            
            cmd += f" \\\n  '{url}'"
            
            commands.append(cmd)
        
        return commands
    
    def _generate_poc_html(self, finding: Finding) -> str:
        """Generate PoC HTML for browser-based vulnerabilities."""
        
        if finding.type.upper() == "XSS":
            return f"""<!DOCTYPE html>
<html>
<head>
    <title>XSS PoC - {finding.id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .info {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .payload {{ background: #fff3cd; padding: 10px; border-radius: 3px; font-family: monospace; }}
        .warning {{ color: #856404; }}
    </style>
</head>
<body>
    <h1>XSS Proof of Concept</h1>
    
    <div class="info">
        <p><strong>Finding ID:</strong> {finding.id}</p>
        <p><strong>Target:</strong> {finding.url}</p>
        <p><strong>Parameter:</strong> {finding.parameter or 'N/A'}</p>
        <p><strong>Severity:</strong> {finding.severity.value.upper()}</p>
    </div>
    
    <h2>Payload</h2>
    <div class="payload">{finding.payload or '<script>alert(document.domain)</script>'}</div>
    
    <h2>Reproduction</h2>
    <ol>
        {''.join(f'<li>{step}</li>' for step in finding.reproduction_steps) or '<li>Visit the vulnerable URL with the payload</li>'}
    </ol>
    
    <h2>Impact</h2>
    <p>{finding.impact or 'An attacker could execute arbitrary JavaScript in the context of the victim user session.'}</p>
    
    <p class="warning">⚠️ This PoC is for authorized security testing only.</p>
</body>
</html>"""
        
        elif finding.type.upper() == "CSRF":
            return f"""<!DOCTYPE html>
<html>
<head>
    <title>CSRF PoC - {finding.id}</title>
</head>
<body>
    <h1>CSRF Proof of Concept</h1>
    
    <p><strong>Target:</strong> {finding.url}</p>
    <p><strong>This page will automatically submit the form when loaded.</strong></p>
    
    <form id="csrf_form" action="{finding.endpoint}" method="POST">
        <!-- Add form fields based on the vulnerable endpoint -->
        <input type="hidden" name="action" value="malicious_action" />
    </form>
    
    <script>
        // Uncomment to auto-submit:
        // document.getElementById('csrf_form').submit();
    </script>
    
    <p>⚠️ This PoC is for authorized security testing only.</p>
</body>
</html>"""
        
        elif finding.type.upper() == "CLICKJACKING":
            return f"""<!DOCTYPE html>
<html>
<head>
    <title>Clickjacking PoC - {finding.id}</title>
    <style>
        iframe {{
            width: 100%;
            height: 500px;
            border: 2px solid red;
        }}
        .overlay {{
            position: absolute;
            top: 100px;
            left: 100px;
            background: rgba(255,0,0,0.3);
            padding: 20px;
            pointer-events: none;
        }}
    </style>
</head>
<body>
    <h1>Clickjacking Proof of Concept</h1>
    
    <p><strong>Target:</strong> {finding.url}</p>
    <p>The target page is loaded in an iframe below, demonstrating it can be framed.</p>
    
    <div style="position: relative;">
        <iframe src="{finding.url}"></iframe>
        <div class="overlay">
            Attacker overlay - user thinks they're clicking here
        </div>
    </div>
    
    <p>⚠️ This PoC is for authorized security testing only.</p>
</body>
</html>"""
        
        elif finding.type.upper() == "OPEN_REDIRECT":
            return f"""<!DOCTYPE html>
<html>
<head>
    <title>Open Redirect PoC - {finding.id}</title>
</head>
<body>
    <h1>Open Redirect Proof of Concept</h1>
    
    <p><strong>Vulnerable URL:</strong></p>
    <code>{finding.url}</code>
    
    <p><strong>Click the link below to test:</strong></p>
    <a href="{finding.url}" target="_blank">Test Redirect</a>
    
    <h2>Impact</h2>
    <p>{finding.impact or 'An attacker could redirect users to malicious websites for phishing attacks.'}</p>
    
    <p>⚠️ This PoC is for authorized security testing only.</p>
</body>
</html>"""
        
        else:
            return f"""<!DOCTYPE html>
<html>
<head>
    <title>PoC - {finding.id}</title>
</head>
<body>
    <h1>Proof of Concept - {finding.type}</h1>
    
    <p><strong>Finding ID:</strong> {finding.id}</p>
    <p><strong>Target:</strong> {finding.url}</p>
    <p><strong>Severity:</strong> {finding.severity.value.upper()}</p>
    
    <h2>Evidence</h2>
    <pre>{finding.evidence}</pre>
    
    <h2>Reproduction Steps</h2>
    <ol>
        {''.join(f'<li>{step}</li>' for step in finding.reproduction_steps)}
    </ol>
    
    <p>⚠️ This PoC is for authorized security testing only.</p>
</body>
</html>"""
    
    def generate_h1_report_attachment(self, package: EvidencePackage) -> Dict:
        """Generate H1-formatted attachment information."""
        attachments = []
        
        for screenshot in package.screenshots:
            attachments.append({
                "type": "screenshot",
                "path": screenshot,
                "filename": Path(screenshot).name
            })
        
        if package.poc_html_path:
            attachments.append({
                "type": "poc",
                "path": package.poc_html_path,
                "filename": "poc.html"
            })
        
        if package.poc_script_path:
            attachments.append({
                "type": "script",
                "path": package.poc_script_path,
                "filename": "reproduce.sh"
            })
        
        if package.video_path:
            attachments.append({
                "type": "video",
                "path": package.video_path,
                "filename": Path(package.video_path).name
            })
        
        return {
            "finding_id": package.finding_id,
            "evidence_dir": package.evidence_dir,
            "attachments": attachments,
            "reproduction_steps": [
                {
                    "step": s.step_number,
                    "action": s.action,
                    "description": s.description
                }
                for s in package.reproduction_steps
            ],
            "curl_commands": package.curl_commands
        }


async def test_evidence_collector():
    """Test EvidenceCollector functionality."""
    print("=" * 60)
    print("Testing EvidenceCollector")
    print("=" * 60)
    
    from .tool_api import Finding, Severity
    
    test_finding = Finding(
        id="test_xss_001",
        type="XSS",
        severity=Severity.HIGH,
        url="https://example.com/search?q=test",
        endpoint="https://example.com/search",
        parameter="q",
        payload="<script>alert(1)</script>",
        evidence="XSS payload executed, alert box displayed",
        reproduction_steps=[
            "Navigate to https://example.com/search",
            "Enter payload in search field",
            "Submit form",
            "Observe alert box"
        ],
        impact="An attacker could steal session cookies and perform actions as the victim user."
    )
    
    collector = EvidenceCollector(Path("/tmp/evidence_test"))
    package = await collector.collect_for_finding(test_finding)
    
    print(f"\n✅ Evidence package created:")
    print(f"   Finding: {package.finding_id}")
    print(f"   Screenshots: {len(package.screenshots)}")
    print(f"   cURL commands: {len(package.curl_commands)}")
    print(f"   PoC HTML: {package.poc_html_path}")
    print(f"   Evidence dir: {package.evidence_dir}")
    
    report = collector.generate_h1_report_attachment(package)
    print(f"\n   H1 Report attachments: {len(report['attachments'])}")


if __name__ == "__main__":
    asyncio.run(test_evidence_collector())
