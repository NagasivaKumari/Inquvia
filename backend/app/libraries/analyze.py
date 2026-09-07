"""Shared analysis building blocks (mirrors investigation/analyze.ts)."""
from ..libraries import storage

VALID_CONCLUSIONS = [
    "likely_genuine", "likely_misleading", "suspicious",
    "insufficient_evidence", "inconclusive",
]
VALID_RISKS = ["low", "moderate", "high", "unknown"]
VALID_SIGNALS = ["supporting", "contradictory", "uncertain"]


def heuristic_analysis(inv: dict, evidence: list[dict]) -> dict:
    supporting = [e for e in evidence if e.get("signal") == "supporting" or e.get("supportsClaim")]
    contradicting = [e for e in evidence if e.get("signal") == "contradictory" or e.get("contradictsClaim")]

    # Check for direct verdicts from evidence services
    verdicts = [e.get("metadata", {}).get("verdict") for e in evidence if e.get("metadata", {}).get("verdict")]

    if len(contradicting) > 0 and len(supporting) > 0:
        conclusion = "suspicious"
    elif len(contradicting) >= 1:
        conclusion = "likely_misleading"
    elif len(supporting) >= 1:
        conclusion = "likely_genuine"
    elif "insufficient_evidence" in verdicts:
        conclusion = "insufficient_evidence"
    else:
        conclusion = "inconclusive"

    if evidence:
        conclusion_text = (
            f"Based on {len(evidence)} acquired evidence item(s), {len(supporting)} supporting "
            f"and {len(contradicting)} contradicting, Inquvia reached the assessment below."
        )
    else:
        conclusion_text = "Insufficient evidence acquired to render a supported assessment."

    # Use actual evidence service confidence if available
    item_confidences = [float(e.get("confidence", 0)) for e in evidence if e.get("confidence") is not None and float(e.get("confidence", 0)) > 0]
    if item_confidences:
        confidence = round(sum(item_confidences) / len(item_confidences))
    elif supporting:
        confidence = round(max(0, min(100, (len(supporting) / len(evidence)) * 100)))
    else:
        confidence = 0

    # Collect findings across all observations and facts
    findings = []
    for e in evidence:
        src = e.get("source", "Evidence Service")
        meta = e.get("metadata") or {}
        obs = meta.get("observations") or []
        facts = meta.get("facts") or []
        if obs:
            for o in obs:
                t = o.get("text") if isinstance(o, dict) else str(o)
                if t and f"{src}: {t}" not in findings:
                    findings.append(f"{src}: {t}")
        elif facts:
            for f in facts:
                t = f.get("text") if isinstance(f, dict) else str(f)
                if t and f"{src}: {t}" not in findings:
                    findings.append(f"{src}: {t}")
        else:
            findings.append(f"{src}: {e.get('finding', '')}")

    # Collect limitations from evidence items
    limitations = []
    for e in evidence:
        meta = e.get("metadata") or {}
        for lim in meta.get("limitations") or []:
            if lim and lim not in limitations:
                limitations.append(lim)

    acquisitions_len = len(inv.get("acquisitions") or [])
    if len(evidence) < acquisitions_len:
        limitations.append("Some evidence checks did not complete")
    elif len(evidence) == 0:
        limitations.append("No external evidence was acquired")
    elif not limitations:
        limitations.append("Assessment is limited to the external evidence services that were configured and settled")

    def contradictory_weight(items):
        c = len([e for e in items if e.get("signal") == "contradictory" or e.get("contradictsClaim")])
        if c == 0:
            return "low"
        if c <= 1:
            return "moderate"
        return "high"

    return {
        "conclusion": conclusion,
        "conclusionText": conclusion_text,
        "confidence": confidence,
        "risk": contradictory_weight(evidence),
        "findings": findings if findings else [f"{e.get('source','')}: {e.get('finding','')}" for e in evidence],
        "limitations": limitations,
        "contradictions": [e["finding"] for e in contradicting],
    }


def build_evidence_graph(inv: dict, evidence: list[dict]) -> dict:
    nodes = []
    edges = []
    claim_id = "node_claim"
    nodes.append({"id": claim_id, "kind": "claim", "label": (inv.get("question") or "")[:80]})

    for e in evidence:
        eid = e.get("id")
        source_id = f"node_source_{eid}"
        ev_id = f"node_ev_{eid}"
        nodes.append({"id": source_id, "kind": "source", "label": e.get("source")})
        nodes.append({"id": ev_id, "kind": "evidence", "label": e.get("type"), "evidenceId": eid})
        edges.append({"from": ev_id, "to": source_id, "relation": "derived_from"})
        signal = e.get("signal")
        if signal == "supporting" or e.get("supportsClaim"):
            relation = "supports"
        elif signal == "contradictory" or e.get("contradictsClaim"):
            relation = "contradicts"
        else:
            relation = "related_to"
        edges.append({"from": ev_id, "to": claim_id, "relation": relation})

    finding_id = "node_finding"
    findings = inv.get("findings") or []
    nodes.append({"id": finding_id, "kind": "finding", "label": findings[0] if findings else "Analysis result"})
    edges.append({"from": finding_id, "to": claim_id, "relation": "verified_by"})

    nodes.append({"id": "node_assessment", "kind": "assessment", "label": inv.get("conclusion")})
    top_ev = f"node_ev_{evidence[0]['id']}" if evidence else finding_id
    edges.append({"from": top_ev, "to": "node_assessment", "relation": "related_to"})

    return {"nodes": nodes, "edges": edges}


def clamp_confidence(v: float) -> float:
    if v is None or not (_isnumber(v)):
        return 0
    return round(min(100, max(0, float(v))))


def _isnumber(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def normalize_conclusion(raw: str | None):
    if not raw:
        return None
    v = raw.strip().lower().replace(" ", "_")
    return v if v in VALID_CONCLUSIONS else None


read_stored_text = storage.read_stored_text
read_stored_file_base64 = storage.read_stored_file_base64