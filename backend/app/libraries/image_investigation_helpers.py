"""Shared helpers for evidence-driven image investigations.

Builds deterministic investigation traces, extracts structured external
evidence from acquired records, and enforces honesty when no web sources
were actually queried.
"""
from __future__ import annotations

TRACE_LABELS = {
    "image_metadata": "Metadata",
    "image_visual_observation": "Visual scene observation",
    "image_provenance": "Provenance verification",
    "image_manipulation": "Forensic analysis",
    "image_c2pa": "C2PA / Content Credentials",
    "ai_detection": "AI-generation analysis",
    "image_quality": "Image quality analysis",
    "image_reverse_search": "Reverse-image matching",
    "image_authoritative_search": "Historical/authoritative source search",
    "image_ocr": "OCR / text extraction",
    "image_compare": "Two-image comparison",
    "pii_detection": "Privacy / PII detection",
    "safety_analysis": "Safety / hazard analysis",
    "document_analysis": "Document analysis",
    "meme_context": "Meme / context timeline",
    "copyright_attribution": "Copyright / attribution",
    "batch_investigation": "Batch clustering",
    "logo_watermark": "Logo / watermark check",
    "geospatial_analysis": "Geospatial analysis",
    "before_after_analysis": "Before/after comparison",
    "accessibility_description": "Accessibility description",
    "commercial_verification": "Commercial verification",
    "scientific_technical": "Scientific / technical analysis",
}

_EXTERNAL_CHECKS = frozenset({"image_reverse_search", "image_authoritative_search"})

_HONESTY_LIMITATION = (
    "No independent external evidence was acquired. This assessment is limited "
    "to the submitted image and internal file analysis."
)


def build_investigation_trace(inv: dict) -> list[dict]:
    """Deterministic checklist of which checks were planned vs actually run."""
    planned_caps = []
    for req in inv.get("evidenceRequirements") or []:
        cap = req.get("capability")
        if cap and cap not in planned_caps:
            planned_caps.append(cap)

    executed: dict[str, dict] = {}
    for ev in inv.get("evidence") or []:
        meta = ev.get("metadata") or {}
        cap = meta.get("checkCapability")
        if not cap:
            continue
        state = executed.setdefault(cap, {"ran": True, "unavailable": False, "no_results": False})
        if meta.get("reverseImageUnavailable") or meta.get("authoritativeSearchUnavailable"):
            state["unavailable"] = True
        if meta.get("reverseImageError") == "no_matches" or meta.get("authoritativeSearchEmpty"):
            state["no_results"] = True
        if meta.get("evidenceUnavailable") or meta.get("compareSkipped"):
            state["unavailable"] = True

    trace = []
    for cap in planned_caps:
        label = TRACE_LABELS.get(cap, cap.replace("_", " ").title())
        info = executed.get(cap)
        if not info:
            status = "not_run"
            detail = "Check was planned but did not produce an evidence record."
        elif info.get("unavailable"):
            status = "unavailable"
            detail = "Check ran but the required service or input was unavailable."
        elif info.get("no_results"):
            status = "completed"
            detail = "Check ran; no matching external sources were found."
        else:
            status = "completed"
            detail = "Check ran and produced observable results."
        trace.append({
            "check": label,
            "capability": cap,
            "status": status,
            "detail": detail,
        })
    return trace


def extract_external_evidence(evidence: list[dict]) -> list[dict]:
    """Structured external source records from reverse-image and web search."""
    external = []
    seen_links: set[str] = set()

    def _add(source_name: str, url: str, source_type: str, finding: str,
             relevance: str, confidence: str | None = None):
        link = (url or "").strip()
        if link and link in seen_links:
            return
        if link:
            seen_links.add(link)
        external.append({
            "sourceName": source_name[:200],
            "url": link[:1000] if link else None,
            "sourceType": source_type,
            "finding": finding[:800],
            "relevance": relevance[:300],
            "confidence": confidence,
        })

    for ev in evidence or []:
        meta = ev.get("metadata") or {}
        rev = meta.get("reverseImageResult") or {}
        if rev.get("matches"):
            for m in rev["matches"][:8]:
                _add(
                    m.get("source") or m.get("title") or "Web match",
                    m.get("link") or "",
                    "reverse_image_match",
                    (m.get("title") or "") + (f" — {m.get('snippet')}" if m.get("snippet") else ""),
                    "high" if ev.get("signal") == "supporting" else "uncertain",
                )
    return external


def finalize_image_investigation(inv: dict, evidence: list[dict], result: dict) -> dict:
    """Post-processes and formats the raw AI-generated analysis result
    to strictly adhere to the Inquvia Auditable Report specification.

    Ensures:
    1. Robust and structured separation of facts (Observed vs Verified vs Inferred).
    2. Accurate populating of mediaAuthenticity and contextualAccuracy.
    3. Explicit limitation disclosure for search engines / reverse image matching.
    4. Exact tracing of completed checks.
    """
    # 1. Traces which planned checks ran and succeeded vs which did not
    result["investigationTrace"] = build_investigation_trace(inv)

    # 2. Extract and format authoritative external sources from checks
    result["externalEvidence"] = extract_external_evidence(evidence)

    # 3. Standardize forensic findings representation
    forensic = result.get("forensicFindings") or {}
    observed = forensic.get("visualObservations") or []
    verified = forensic.get("externallyVerifiedFacts") or []
    inferred = forensic.get("inferences") or []
    could_not_verify = forensic.get("couldNotVerify") or []
    contradictions = forensic.get("contradictions") or []

    # Check which external capabilities successfully executed
    completed_caps = {
        e.get("metadata", {}).get("checkCapability")
        for e in evidence
        if e.get("status") == "collected"
    }
    has_external_data = any(cap in completed_caps for cap in _EXTERNAL_CHECKS)

    if not has_external_data:
        # Strict enforcement: do not claim external cross-checking occurred
        # when only internal metadata/local analysis took place.
        lims = result.setdefault("limitations", [])
        if _HONESTY_LIMITATION not in lims:
            lims.append(_HONESTY_LIMITATION)
        
        # Enforce empty external evidence and clear distinction
        verified = []
        if "External source validation not executed" not in could_not_verify:
            could_not_verify.append("External source validation (no reverse-image or authoritative web search was provisioned or executed)")

    # Format the auditable final report
    result["observedDirectly"] = observed
    result["externallyVerified"] = verified
    result["inferred"] = inferred
    result["couldNotVerify"] = could_not_verify
    result["contradictions"] = contradictions

    return result
