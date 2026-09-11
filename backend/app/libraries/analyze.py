"""Shared analysis building blocks (mirrors investigation/analyze.ts)."""
from ..libraries import storage

VALID_CONCLUSIONS = [
    "likely_genuine", "likely_misleading", "suspicious",
    "insufficient_evidence", "inconclusive",
]
VALID_RISKS = ["low", "moderate", "high", "unknown"]
VALID_SIGNALS = ["supporting", "contradictory", "uncertain"]


def redundant_evidence_ids(inv: dict, evidence: list[dict]) -> set:
    """Ids of evidence that must NOT count as independent confirmation.

    Two kinds are de-weighted (kept in the evidence trail, excluded from the
    confidence / signal tallies):
      - duplicate copies: the provider's duplicates analysis is combined into
        connected sets; the earliest-acquired copy of each set stays primary,
        the rest are de-weighted.
      - dependent/derived evidence: a provider-stated independent=False.
    Unknown independence is kept (counted) because there is no basis to
    de-weight it; a provider-stated independent=True counts normally.
    """
    duplicate_pairs = {}
    try:
        raw = inv.get("duplicates") or {}
        pair_list = raw.get("duplicates") if isinstance(raw, dict) else raw
        for p in pair_list or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                duplicate_pairs.setdefault(p[0], []).append(p[1])
                duplicate_pairs.setdefault(p[1], []).append(p[0])
    except Exception:
        duplicate_pairs = {}

    rank = {e["id"]: i for i, e in enumerate(evidence)}
    adjacency = {}
    for a, bs in duplicate_pairs.items():
        adjacency.setdefault(a, set()).update(bs)
        for b in bs:
            adjacency.setdefault(b, set()).update([a])

    redundant = set()
    seen = set()
    for eid in rank:
        if eid in seen or eid not in adjacency:
            continue
        comp, stack = [], [eid]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.append(n)
            for m in adjacency.get(n, ()):
                if m not in seen:
                    stack.append(m)
        primary = min(comp, key=lambda x: rank.get(x, len(evidence) + 1))
        for m in comp:
            if m != primary:
                redundant.add(m)

    for e in evidence:
        if e.get("independent") is False:
            redundant.add(e["id"])
    return redundant


def heuristic_analysis(inv: dict, evidence: list[dict]) -> dict:
    # De-weight duplicate/dependent evidence: it stays in the trail but is not
    # counted as independent confirmation (see redundant_evidence_ids).
    redundant = redundant_evidence_ids(inv, evidence)
    effective = [e for e in evidence if e["id"] not in redundant]
    supporting = [e for e in effective if e.get("signal") == "supporting" or e.get("supportsClaim")]
    contradicting = [e for e in effective if e.get("signal") == "contradictory" or e.get("contradictsClaim")]

    # Check for direct verdicts from evidence services
    verdicts = [e.get("metadata", {}).get("verdict") for e in effective if e.get("metadata", {}).get("verdict")]

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
        if supporting or contradicting:
            conclusion_text = (
                f"Based on {len(evidence)} acquired evidence item(s), {len(supporting)} "
                f"established support and {len(contradicting)} established contradiction."
            )
        else:
            conclusion_text = (
                f"Based on {len(evidence)} acquired evidence item(s), no supporting or "
                "contradicting evidence relationship was established. Zero counts mean no "
                "relationship was asserted — the evidence neither supported nor disproved "
                "the claim."
            )
    else:
        conclusion_text = "Insufficient evidence acquired to render a supported assessment."

    # Use actual evidence service confidence if available (over non-redundant
    # items only, so copied/dependent evidence can't inflate the answer)
    item_confidences = [float(e.get("confidence", 0)) for e in effective if e.get("confidence") is not None and float(e.get("confidence", 0)) > 0]
    if item_confidences:
        confidence = round(sum(item_confidences) / len(item_confidences))
    elif supporting:
        confidence = round(max(0, min(100, (len(supporting) / max(1, len(effective))) * 100)))
    else:
        confidence = 0

    # Collect findings across all observations and facts (the full trail, including
    # de-weighted items)
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

    if redundant:
        limitations.append(
            f"{len(redundant)} duplicate/dependent evidence item(s) were de-weighted "
            "(kept in the evidence trail but not counted as independent confirmation).")

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
        "risk": contradictory_weight(effective),
        "findings": findings if findings else [f"{e.get('source','')}: {e.get('finding','')}" for e in evidence],
        "limitations": limitations,
        "contradictions": [e["finding"] for e in contradicting],
        "evidenceRelationships": {
            "supporting": len(supporting),
            "contradicting": len(contradicting),
            "established": bool(supporting or contradicting),
        },
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


async def run_ai_ocr(data: bytes, mime: str | None, pages: list[dict]) -> dict:
    """The app's existing OCR capability: hand the scanned attachment to the
    configured multimodal AI and collect verbatim per-page transcriptions.

    Returns {page_number: text} for the pages the model could read; {} when no
    OCR-capable provider is configured, the attachment can't be reached, or the
    model produced nothing. Text is the model's transcription of the rendered
    page — OCR-derived evidence, labeled as such, never invented from nothing.
    """
    if not data or not pages:
        return {}
    try:
        import base64
        from ..libraries import ai as ai_lib
        part = {"file": {"mimeType": mime or "application/octet-stream",
                         "base64": base64.b64encode(data).decode("ascii")}}
        prompt = (
            "You are the OCR step of an evidence pipeline. The attached document contains pages "
            "without a selectable text layer. Transcribe the visible content VERBATIM for every page: "
            "exact words, numbers and dates as printed; do not summarize, interpret, or add anything "
            "not present on the page. If a page is blank, transcribe it as an empty string. "
            'Return ONLY JSON: {"pages": [{"page": <number>, "text": "<verbatim transcription>"}, ...]}'
        )
        raw = await ai_lib.call_ai_with_parts(prompt, [part])
        payload = ai_lib.parse_ai_json(raw)
        out = {}
        for item in (payload or {}).get("pages") or []:
            if isinstance(item, dict) and isinstance(item.get("page"), int) and isinstance(item.get("text"), str):
                t = item["text"].strip()
                if t:
                    out[item["page"]] = t
        return out
    except Exception:
        return {}


read_stored_text = storage.read_stored_text
read_stored_file_base64 = storage.read_stored_file_base64