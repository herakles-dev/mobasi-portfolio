# Excerpt from V5Orchestrator (710 lines total)
# Full source implements 5-phase workflow: intelligence → recon → discovery → vulnerability → validation

#!/usr/bin/env python3
"""
H1-Expert V5 Orchestrator - Main Workflow Coordinator
Orchestrates full hunting workflow: intelligence → recon → scan → validate
Includes Claude checkpoints for human review and approval.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import sys

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Core module imports
from core.h1_api import H1API, VulnerabilityReport
from core.h1_compliance_validator import H1ComplianceValidator
from core.recon_engine import ReconEngine
from core.parallel_scanner import ParallelScanner
from core.bounty_tracker import BountyTracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WorkflowPhase(Enum):
    """Workflow execution phases."""
    INTELLIGENCE = "intelligence"
    RECON = "recon"
    DISCOVERY = "discovery"
    VULNERABILITY = "vulnerability"
    VALIDATION = "validation"
    COMPLETE = "complete"


@dataclass
class WorkflowState:
    """Tracks workflow execution state."""
    program_name: str
    phase: WorkflowPhase
    start_time: datetime
    intelligence_data: Optional[Dict] = None
    recon_results: Optional[Dict] = None
    discovery_results: Optional[Dict] = None
    vulnerability_findings: Optional[List[Dict]] = None
    validation_results: Optional[Dict] = None
    checkpoints_approved: List[str] = None
    
    def __post_init__(self):
        if self.checkpoints_approved is None:
            self.checkpoints_approved = []


@dataclass
class WorkflowResult:
    """Comprehensive workflow results."""
    program_name: str
    execution_time_seconds: float
    phases_completed: List[str]
    total_assets_discovered: int
    vulnerabilities_found: int
    high_severity_count: int
    validated_findings: int
    compliance_passed: bool
    ready_for_submission: bool
    detailed_findings: List[Dict]
    intelligence_summary: Dict
    recommendations: List[str]


class V5Orchestrator:
    """
    Main V5 workflow orchestrator.
    Coordinates intelligence loading, reconnaissance, scanning, and validation.
    """
    
    def __init__(self, program_name: str, output_dir: Path = None):
        """
        Initialize orchestrator for a specific program.
        
        Args:
            program_name: Target HackerOne program name
            output_dir: Directory for results (default: ./results/{program_name})
        """
        self.program_name = program_name
        self.output_dir = output_dir or Path(f"./results/{program_name}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize components
        self.compliance_validator = H1ComplianceValidator()
        self.h1_api = H1API()
        self.bounty_tracker = BountyTracker()
        
        # Workflow state
        self.state = WorkflowState(
            program_name=program_name,
            phase=WorkflowPhase.INTELLIGENCE,
            start_time=datetime.now()
        )
        
        # State file for resume capability
        self.state_file = self.output_dir / "workflow_state.json"
        
        logger.info(f"V5 Orchestrator initialized for program: {program_name}")
    
    
    async def load_intelligence(self) -> Dict:
        """
        Load program intelligence from JSON files.
        
        Returns:
            Dictionary with program intelligence data
        """
        logger.info(f"Loading intelligence for {self.program_name}...")
        
        intel_file = Path(__file__).parent.parent / "intelligence" / "programs" / f"{self.program_name}.json"
        
        if not intel_file.exists():
            logger.warning(f"Intelligence file not found: {intel_file}")
            return {
                "program_name": self.program_name,
                "error": "No intelligence file found",
                "recommendation": "Gather intelligence manually or use default scanning"
            }
        
        try:
            with open(intel_file, 'r') as f:
                intelligence = json.load(f)
            
            logger.info(f"Loaded intelligence: {intelligence.get('program_metadata', {}).get('intelligence_version', 'unknown')}")
            
            # Extract key information
            summary = {
                "program_name": self.program_name,
                "response_efficiency": intelligence.get('program_overview', {}).get('response_efficiency', 'N/A'),
                "total_assets": intelligence.get('scope_analysis', {}).get('total_assets', 0),
                "opportunity_score": intelligence.get('strategic_analysis', {}).get('opportunity_assessment', {}).get('overall_score', 0),
                "in_scope_domains": intelligence.get('scope_analysis', {}).get('domains', []),
                "key_vulnerability_trends": intelligence.get('hacktivity_intel', {}).get('vulnerability_trends', []),
                "testing_priorities": intelligence.get('strategic_analysis', {}).get('testing_strategy', {}).get('priority_areas', [])
            }
            
            self.state.intelligence_data = summary
            self.save_state()
            
            return summary
            
        except Exception as e:
            logger.error(f"Error loading intelligence: {e}")
            return {
                "program_name": self.program_name,
                "error": str(e)
            }
    
    
    async def phase_1_recon(self, targets: List[str] = None) -> Dict:
        """
        Phase 1: Reconnaissance - Subdomain enumeration and port scanning.
        
        Args:
            targets: List of root domains to scan (from intelligence if not provided)
        
        Returns:
            Dictionary with discovered assets
        """
        logger.info("=== PHASE 1: RECONNAISSANCE ===")
        
        # Get targets from intelligence if not provided
        if not targets and self.state.intelligence_data:
            targets = self.state.intelligence_data.get('in_scope_domains', [])[:3]  # Limit to top 3
        
        if not targets:
            logger.error("No targets provided and no intelligence available")
            return {"error": "No targets to scan"}
        
        # Claude checkpoint: Review targets
        print("\n" + "="*80)
        print("🔍 CHECKPOINT: Reconnaissance Targets")
        print("="*80)
        print(f"Program: {self.program_name}")
        print(f"Targets to scan: {', '.join(targets)}")
        print("\nAbout to perform:")
        print("  - Subdomain enumeration (subfinder, amass)")
        print("  - Port scanning (masscan, nmap)")
        print("  - HTTP probing (httpx)")
        print("  - Technology detection")
        print("="*80)
        if not self.checkpoint("Start reconnaissance?"):
            return {"error": "Checkpoint not approved", "phase": "recon"}
        
        all_results = {
            "targets_scanned": len(targets),
            "subdomains_found": [],
            "live_hosts": [],
            "open_ports": {},
            "technologies": []
        }
        
        # Run reconnaissance for each target
        for target in targets:
            try:
                logger.info(f"Running reconnaissance on {target}...")
                recon = ReconEngine(target)
                
                # Subdomain enumeration
                subdomains = await recon.enumerate_subdomains()
                all_results["subdomains_found"].extend(subdomains)
                
                # Port scanning on discovered subdomains (limit to first 10)
                for subdomain in subdomains[:10]:
                    ports = await recon.scan_ports(subdomain)
                    if ports:
                        all_results["open_ports"][subdomain] = ports
                        all_results["live_hosts"].append(subdomain)
                
                logger.info(f"Found {len(subdomains)} subdomains for {target}")
                
            except Exception as e:
                logger.error(f"Error during recon of {target}: {e}")
        
        # Summary
        all_results["summary"] = {
            "total_subdomains": len(all_results["subdomains_found"]),
            "total_live_hosts": len(all_results["live_hosts"]),
            "total_open_ports": sum(len(ports) for ports in all_results["open_ports"].values())
        }
        
        self.state.recon_results = all_results
        self.state.phase = WorkflowPhase.DISCOVERY
        self.save_state()
        
        # Save results
        output_file = self.output_dir / "phase1_recon.json"
        with open(output_file, 'w') as f:
            json.dump(all_results, f, indent=2)
        
        logger.info(f"Recon complete. Results saved to {output_file}")
        return all_results
