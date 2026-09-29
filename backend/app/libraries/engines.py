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
            # Signal direction must be part of the fingerprint. Two items can
            # carry the same observation text and disagree about what it means;
            # collapsing them drops the contradiction and silently flips the
            # verdict (supporting + contradictory looked like a match pair and
            # returned likely_genuine instead of suspicious). Same wording with
            # the same signal is still a duplicate.
            signal = "{}|{}|{}".format(
                e.get("signal"),
                bool(e.get("supportsClaim")),
                bool(e.get("contradictsClaim")),
            )
            fingerprint = (
                f"{e.get('type')}|{e.get('source')}|{signal}|"
                f"{re.sub(r'\\W+', ' ', (e.get('finding') or '').lower())}"
            )
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

# A "Label: 123" style finding carries a checkable fact. Two items claiming the
# same label with materially different numbers are a contradiction regardless of
# what the model says. ponytail: label + first number only, 5% tolerance; this
# is the floor, not a replacement for the semantic pass below.
_NUMERIC_LABEL = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z_-]{1,30})\s*(?:is|=|:)\s*\$?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LABEL_NOISE = re.compile(
    r"^(?:page\s+\d+\s+(?:lists?|shows?)|the|report\s+shows?|line\s+item\s+total)\s+",
    re.IGNORECASE,
)
_NUM_TOLERANCE = 0.05


def _numeric_claims(evidence: List[Dict[str, Any]]) -> Dict[str, List[tuple]]:
    """Map normalized label -> [(value, evidence_id)] across evidence findings."""
    out: Dict[str, List[tuple]] = {}
    for e in evidence:
        m = _NUMERIC_LABEL.search((e.get("finding") or "").strip())
        if not m:
            continue
        label = _LABEL_NOISE.sub("", m.group("label")).strip().lower()
        if not label:
            continue
        try:
            value = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        out.setdefault(label, []).append((value, e.get("id")))
    return out


def numeric_conflicts(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic contradiction pass: same label, materially different value."""
    conflicts = []
    for label, items in _numeric_claims(evidence).items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (va, ida), (vb, idb) = items[i], items[j]
                if ida == idb or ida is None or idb is None:
                    continue
                hi = max(abs(va), abs(vb))
                if hi and abs(va - vb) / hi > _NUM_TOLERANCE:
                    conflicts.append({
                        "evidence_id1": ida,
                        "evidence_id2": idb,
                        "description": f"Conflicting values for '{label}': {va:g} vs {vb:g}.",
                        "detectedBy": "numeric",
                    })
    return conflicts


class ContradictionEngine:
    """Compares evidence for semantic contradictions."""

    @staticmethod
    async def find_contradictions(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deterministic numeric conflicts first, then the semantic pass.

        The numeric pass is authoritative and never dropped; the model's pairs
        are merged in only where they are not already covered.
        """
        deterministic = numeric_conflicts(evidence)

        system_prompt = (
            "Analyze the following evidence items and identify any semantic contradictions "
            "between them. Return a JSON list of objects, each containing 'evidence_id1', "
            "'evidence_id2', and a 'description' of the contradiction."
        )
        parts = [{"text": json.dumps(evidence)}]

        raw_result = await call_ai_with_parts(system_prompt + few_shot_block("contradictions"), parts, task="contradictions")
        result = parse_ai_json(raw_result)
        ai = result if isinstance(result, list) else []

        seen = set()
        for c in deterministic:
            seen.add((c["evidence_id1"], c["evidence_id2"]))
            seen.add((c["evidence_id2"], c["evidence_id1"]))
        merged = list(deterministic)
        for c in ai:
            if not isinstance(c, dict):
                continue
            pair = (c.get("evidence_id1"), c.get("evidence_id2"))
            if pair in seen or (pair[1], pair[0]) in seen:
                continue
            seen.add(pair)
            merged.append(c)
        return merged


if __name__ == "__main__":
    ev = [
        {"id": "1", "finding": "Attendees: 300"},
        {"id": "2", "finding": "Attendees: 42"},
        {"id": "3", "finding": "Total: $1,240.00"},
        {"id": "4", "finding": "Page lists Total: $1,240.00"},
    ]
    c = numeric_conflicts(ev)
    assert len(c) == 1, c
    assert {c[0]["evidence_id1"], c[0]["evidence_id2"]} == {"1", "2"}, c
    assert c[0]["detectedBy"] == "numeric"
    assert numeric_conflicts([ev[2], ev[3]]) == []
    assert numeric_conflicts([{"id": "9", "finding": "title=Widget Pro"}]) == []
    print("ContradictionEngine numeric self-check OK")

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

        if isinstance(result, dict) and result.get("verified") is not None:
            return result

        # Fail CLOSED, not open. A provider outage must never look like a
        # finding: `verified: False` here would read as "the evidence does not
        # support this claim" and contradict it. Flag it as unavailable and
        # leave confidence unset so it cannot be averaged in as a low score.
        return {
            "verified": None,
            "unsupported_claims": [],
            "contradictions": [],
            "missing_objectives": [],
            "confidence_score": None,
            "verificationUnavailable": True,
            "unavailableReason": "No model provider returned a usable verification.",
        }
