"""Shared analysis building blocks (mirrors investigation/analyze.ts)."""
from ..libraries import storage, engines

VALID_CONCLUSIONS = [
    "likely_genuine", "likely_misleading", "suspicious",
    "insufficient_evidence", "inconclusive", "answered",
]
VALID_RISKS = ["low", "moderate", "high", "unknown"]
VALID_SIGNALS = ["supporting", "contradictory", "uncertain", "observed"]


def redundant_evidence_ids(inv: dict, evidence: list[dict]) -> set:
    """Ids of evidence that must NOT count as independent confirmation."""
    return engines.DuplicateDependencyEngine.detect_redundant(evidence)


def heuristic_analysis(inv: dict, evidence: list[dict]) -> dict:
    """Shared analysis building blocks (mirrors investigation/analyze.ts)."""
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
    
    # --- AUGMENTED CALIBRATION ---
    # Weigh directness and reliability (Additive enhancement)
    rel_weights = {"high": 1.0, "moderate": 0.7, "low": 0.3, "unknown": 0.5}
    direct_weights = {"direct": 1.0, "indirect": 0.5}
    
    calibrated_confidences = []
    for e in effective:
        meta = e.get("metadata") or {}
        # Service-provided metadata vs heuristic fallback
        rel = rel_weights.get(meta.get("reliability", "unknown"), 0.5)
        direc = direct_weights.get(meta.get("directness", "indirect"), 0.5)
        # Combine service confidence with calibration
        base = float(e.get("confidence") or 50) / 100
        calibrated_confidences.append(base * rel * direc * 100)
    
    if calibrated_confidences:
        confidence = round(sum(calibrated_confidences) / len(calibrated_confidences))
    elif item_confidences:
        confidence = round(sum(item_confidences) / len(item_confidences))
    elif supporting:
        confidence = round(max(0, min(100, (len(supporting) / max(1, len(effective))) * 100)))
    else:
        confidence = 0
    # -----------------------------

    # Collect findings across all observations and facts (the full trail, including
    # de-weighted items)
    findings = []
    for e in evidence:
        src = e.get("source", "Evidence Service")
        meta = e.get("metadata") or {}
        
        # --- AUGMENTED FINDINGS ---
        passage = meta.get("passage") or e.get("finding", "")
        reference = meta.get("reference") or "N/A"
        finding_entry = f"{src}: {passage} [{reference}]"
        
        obs = meta.get("observations") or []
        facts = meta.get("facts") or []
        if obs or facts:
            for item in (obs + facts):
                t = item.get("text") if isinstance(item, dict) else str(item)
                if t and f"{src}: {t}" not in findings:
                    findings.append(f"{src}: {t}")
        else:
            if finding_entry not in findings:
                findings.append(finding_entry)
        # --------------------------

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
        limitations.append("Assessment is based on the evidence services that were configured and settled")

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
    """Build a claim→sub-objective→evidence→conclusion graph.

    Every important final claim is explicitly connected to the evidence that
    supports or contradicts it. Sub-objectives (when present) are intermediate
    nodes between the top-level claim and the evidence items.
    """
    nodes = []
    edges = []
    claim_id = "node_claim"
    nodes.append({"id": claim_id, "kind": "claim", "label": (inv.get("question") or "")[:80]})

    # Sub-objective nodes (produced by the image analyzer's decomposition step)
    sub_objectives = inv.get("subObjectives") or []
    sub_node_ids = {}
    for i, sub in enumerate(sub_objectives):
        if not isinstance(sub, dict):
            continue
        sid = f"node_sub_{i}"
        sub_node_ids[i] = sid
        status = sub.get("status") or "inconclusive"
        nodes.append({"id": sid, "kind": "sub_objective",
                      "label": sub.get("objective") or f"Sub-objective {i + 1}",
                      "status": status,
                      "evidenceLevel": sub.get("evidenceLevel") or "unknown"})
        edges.append({"from": claim_id, "to": sid, "relation": "requires"})

    # Deterministic computation node: connects the question (claim) through
    # the calculation to the computed evidence, so a calculation that directly
    # establishes the answer is never shown as 0 supporting.
    calc_id = None
    computation = inv.get("computation") or {}
    if computation.get("metrics"):
        calc_id = "node_calculation"
        label = f"Calculation: {computation.get('parser') or 'structured'} analysis of {computation.get('source') or 'document'} ({computation.get('recordsProcessed')}/{computation.get('recordsAvailable')} records)"
        nodes.append({"id": calc_id, "kind": "calculation", "label": label,
                      "complete": bool(computation.get("complete"))})
        edges.append({"from": claim_id, "to": calc_id, "relation": "requires"})

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

        # Connect evidence to sub-objective nodes when present, else to claim
        if sub_node_ids:
            # Attach to the first sub-objective whose evidenceLevel matches the
            # evidence type, or fall back to the claim node.
            cap = (e.get("metadata") or {}).get("checkCapability") or ""
            matched = False
            for i, sub in enumerate(sub_objectives):
                if not isinstance(sub, dict):
                    continue
                level = sub.get("evidenceLevel") or ""
                # image metadata/provenance → observed/inferred sub-objectives
                if cap in ("image_provenance", "image_metadata",
                           "image_manipulation", "image_reverse_search") and level in ("observed", "inferred"):
                    edges.append({"from": ev_id, "to": sub_node_ids[i], "relation": relation})
                    matched = True
                    break
            if not matched:
                edges.append({"from": ev_id, "to": claim_id, "relation": relation})
        else:
            edges.append({"from": ev_id, "to": claim_id, "relation": relation})
        # Computation-derived evidence is produced by a deterministic
        # calculation over the source, which itself answers the question.
        if (e.get("metadata") or {}).get("origin") == "computation" and calc_id:
            edges.append({"from": ev_id, "to": calc_id, "relation": "produced_by"})

    # Assessment node connected to the conclusion
    conclusion = inv.get("conclusion") or "unknown"
    assessment_id = "node_assessment"
    nodes.append({"id": assessment_id, "kind": "assessment", "label": conclusion})
    # Connect assessment to claim (not to a random evidence item)
    edges.append({"from": assessment_id, "to": claim_id, "relation": "concludes"})

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
    """The app's OCR capability: hand the pages without a readable text layer to
    the configured multimodal AI and collect verbatim per-page transcriptions.

    Pages carrying a rendered image (base64 PNG) are sent as images — this is
    the reliable path for scanned pages and pages a broken text layer could not
    fully cover. When no per-page images are available (fallback callers), the
    whole attachment is sent instead. Returns {page_number: text} for the pages
    the model could read; {} when no OCR-capable provider is configured,
    rendering is unavailable, or the model produced nothing. Text is the
    model's transcription of the visible page — OCR-derived evidence, labeled
    as such, never invented from nothing.
    """
    if not data or not pages:
        return {}
    try:
        import base64
        from ..libraries import ai as ai_lib

        parts = []
        if any(p.get("image") for p in pages):
            for p in pages:
                if p.get("image"):
                    parts.append({"file": {"mimeType": "image/png", "base64": p["image"]}})
                    parts.append({"text": f"PAGE {p['page']} (transcribe this page verbatim)"})
        else:
            parts.append({"file": {"mimeType": mime or "application/octet-stream",
                                   "base64": base64.b64encode(data).decode("ascii")}})

        prompt = (
            "You are the OCR step of an evidence pipeline. The attached document pages have no "
            "usable selectable text layer. Transcribe the visible content VERBATIM for every page: "
            "exact words, numbers and dates as printed; do not summarize, interpret, or add anything "
            "not present on the page. If a page contains TABLES or structured layouts, preserve the "
            "structure: keep each row's cells in order and separate columns with ' | ' so row/column "
            "relationships stay intact; do not reorder cells or merge values across rows. If a page "
            "is blank, transcribe it as an empty string. "
            'Return ONLY JSON: {"pages": [{"page": <number>, "text": "<verbatim transcription>"}, ...]}'
        )
        raw = await ai_lib.call_ai_with_parts(prompt, parts, task="document")
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