"""
Strengthened engines for autonomous evidence investigation.
Includes: Contradiction Detection, Duplicate Detection, Evidence Gaps, and Claim Verification.
"""
import re
import json
from typing import List, Dict, Any, Optional

from .ai import call_ai_with_parts, parse_ai_json
from .training import call_ai_votes, few_shot_block

class DuplicateDependencyEngine:
    """Detects when separate evidence derives from the same underlying source."""
    
    @staticmethod
    def detect_redundant(evidence: List[Dict[str, Any]]) -> set:
        """
        Fingerprint sources to identify duplicate/dependent material.
        Returns a set of redundant evidence IDs.
        """
        # Logic: 
        # 1. Generate a fingerprint for each evidence item (e.g., hash of finding/source/type)
        # 2. Identify groups of items with the same fingerprint
        # 3. Mark all but one as redundant
        
        fingerprints = {}
        for e in evidence:
            # Simple fingerprinting based on finding + source
            fingerprint = f"{e.get('type')}|{e.get('source')}|{re.sub(r'\\W+', ' ', e.get('finding', '').lower())}"
            fingerprints.setdefault(fingerprint, []).append(e['id'])
            
        redundant = set()
        for fp, ids in fingerprints.items():
            if len(ids) > 1:
                # Keep the first, mark others as redundant
                redundant.update(ids[1:])
        
        # Also include items explicitly marked as dependent
        for e in evidence:
            if e.get("independent") is False:
                redundant.add(e["id"])
                
        return redundant

class ContradictionEngine:
    """Compares evidence for semantic contradictions."""
    
    @staticmethod
    async def find_contradictions(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Performs semantic claim comparison between evidence items."""
        system_prompt = (
            "Analyze the following evidence items and identify any semantic contradictions "
            "between them. Return a JSON list of objects, each containing 'evidence_id1', "
            "'evidence_id2', and a 'description' of the contradiction."
        )
        parts = [{"text": json.dumps(evidence)}]
        
        raw_result = await call_ai_with_parts(system_prompt + few_shot_block("contradictions"), parts, task="contradictions")
        result = parse_ai_json(raw_result)
        
        return result if isinstance(result, list) else []

class GapsEngine:
    """Identifies missing evidence based on investigation objectives."""
    
    @staticmethod
    async def identify_gaps(objectives: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> List[str]:
        """Dynamically identifies missing evidence based on objectives."""
        system_prompt = (
            "Compare the provided investigation objectives with the current evidence set. "
            "Identify which objectives are not covered by any evidence. "
            "Return a JSON list of missing objective descriptions."
        )
        parts = [{"text": f"Objectives: {json.dumps(objectives)}\n\nEvidence: {json.dumps(evidence)}"}]
        
        raw_result = await call_ai_with_parts(system_prompt, parts, task="gaps")
        result = parse_ai_json(raw_result)
        
        return result if isinstance(result, list) else []

class ClaimVerificationGate:
    """Verifies substantive claims against the evidence graph."""
    
    @staticmethod
    async def verify(claim: str, evidence: List[Dict[str, Any]], reasoning: str) -> Dict[str, Any]:
        """
        Final gate before returning an answer. 
        Verifies claims, detects unsupported claims, contradictions, and missing sub-objectives.
        """
        system_prompt = (
            "Verify the claim against the provided evidence and reasoning. "
            "Check for: 1. Is the claim supported? 2. Are there contradictions? "
            "3. Are all sub-objectives covered? Recalculate confidence score (0.0 to 1.0). "
            "Return JSON: {'verified': bool, 'unsupported_claims': list[str], "
            "'contradictions': list[str], 'missing_objectives': list[str], 'confidence_score': float}"
        )
        parts = [{"text": f"Claim: {claim}\n\nEvidence: {json.dumps(evidence)}\n\nReasoning: {reasoning}"}]
        
        raw_result = await call_ai_votes(
            system_prompt + few_shot_block("verify"), parts, task="verify", key="verified"
        )
        result = parse_ai_json(raw_result)
        
        return result if isinstance(result, dict) else {"verified": False, "unsupported_claims": ["Error verifying claims"], "confidence_score": 0.0}
