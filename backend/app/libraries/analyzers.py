"""Capability analyzer registry (mirrors investigation/analyzers.ts)."""
from ..libraries import storage, ai as ai_lib
from ..libraries.analyze import (
    heuristic_analysis,
    clamp_confidence,
    normalize_conclusion,
    VALID_RISKS,
    read_stored_text,
    read_stored_file_base64,
)

REGISTRY = {}


def register_analyzer(capability_id, fn):
    REGISTRY[capability_id] = fn


def get_analyzer(capability_id):
    return REGISTRY.get(capability_id) if capability_id else None


def _to_str_array(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [s[:500] for s in v if isinstance(s, str)]


def _merge_ai_raw(inv, evidence, raw) -> dict:
    base = heuristic_analysis(inv, evidence)
    if not raw:
        return base
    conclusion = normalize_conclusion(raw.get("conclusion")) or base["conclusion"]
    confidence = base["confidence"]
    raw_conf = raw.get("confidence")
    if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool):
        confidence = clamp_confidence(raw_conf)
    elif isinstance(raw_conf, str):
        try:
            confidence = clamp_confidence(float(raw_conf))
        except ValueError:
            pass
    risk = raw.get("risk") if raw.get("risk") in VALID_RISKS else base["risk"]
    ai_findings = _to_str_array(raw.get("findings"))
    findings = ai_findings if ai_findings else base["findings"]
    contradictions = _to_str_array(raw.get("contradictions"))
    limitations = _to_str_array(raw.get("limitations"))
    sources_used = _to_str_array(raw.get("sourcesUsed"))
    uncertainty = raw.get("uncertainty") if isinstance(raw.get("uncertainty"), str) else None
    conclusion_text_raw = raw.get("conclusionText")
    conclusion_text = conclusion_text_raw if isinstance(conclusion_text_raw, str) and conclusion_text_raw else base["conclusionText"]
    if not conclusion_text:
        conclusion_text = (
            f"Assessment: {conclusion.replace('_', ' ').upper()}. "
            f"{' '.join(limitations) if limitations else ''}"
        ).strip()
    return {
        "conclusion": conclusion,
        "conclusionText": conclusion_text,
        "confidence": confidence,
        "risk": risk,
        "findings": findings,
        "contradictions": contradictions if contradictions else base["contradictions"],
        "limitations": limitations if limitations else base["limitations"],
        "uncertainty": uncertainty,
        "sourcesUsed": sources_used,
    }


async def _run_analysis(inv, evidence, system_prompt, context_parts) -> dict:
    if evidence:
        evidence_text = "\n".join(
            f"{i + 1}. [{e.get('signal')}] source={e.get('source')} finding={e.get('finding')} confidence={e.get('confidence')}"
            for i, e in enumerate(evidence)
        )
    else:
        evidence_text = "No external evidence was acquired."
    context_parts.append({"text": f"QUESTION: {inv.get('question')}\n\nACQUIRED EVIDENCE:\n{evidence_text}"})
    raw_text = await ai_lib.call_ai_with_parts(system_prompt, context_parts)
    raw = ai_lib.parse_ai_json(raw_text)
    return _merge_ai_raw(inv, evidence, raw)


def _first_text_input(inv):
    for i in inv.get("inputs") or []:
        if i.get("type") in ("text", "url"):
            return i.get("content")
    return None


def _find_input(inv, input_type):
    for i in inv.get("inputs") or []:
        if i.get("type") == input_type:
            return i
    return None


async def _claim_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's claim verification analyst. Assess whether the submitted claim is supported, contradicted, or unresolved, "
        "using only the acquired evidence and your internal knowledge. Be explicit about uncertainty. Do not claim a conclusion you cannot support. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    claim = _first_text_input(inv) or inv.get("question")
    return await _run_analysis(inv, evidence, system_prompt, [{"text": f"CLAIM: {claim}"}])


async def _image_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's image forensics analyst. Inspect the provided image for signs of manipulation, generative-AI artifacts, or provenance inconsistencies, "
        "together with the acquired evidence. Do not claim verified authenticity — express confidence honestly and state limitations. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    input_ = _find_input(inv, "image")
    parts = []
    if input_ and input_.get("filePath"):
        f = read_stored_file_base64(input_["filePath"])
        if f:
            parts.append({"file": f})
    context_text = (input_.get("content") if input_ else None) or _first_text_input(inv) or ""
    parts.append({"text": f"IMAGE_CONTEXT: {context_text}"})
    return await _run_analysis(inv, evidence, system_prompt, parts)


async def _video_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's video forensics analyst. Assess the submitted video for temporal consistency, manipulation, or context issues using the video content "
        "(when provided) and the acquired evidence. Express confidence honestly; explicit uncertainty is expected. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    input_ = _find_input(inv, "video")
    parts = []
    if input_ and input_.get("filePath"):
        f = read_stored_file_base64(input_["filePath"])
        if f:
            parts.append({"file": f})
    context_text = (input_.get("content") if input_ else None) or _first_text_input(inv) or ""
    parts.append({"text": f"VIDEO_CONTEXT: {context_text}"})
    return await _run_analysis(inv, evidence, system_prompt, parts)


async def _document_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's document forensics analyst. Extract claims from the provided document, identify internal inconsistencies, and flag suspicious or "
        "altered content, together with acquired evidence. Express confidence honestly. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    input_ = _find_input(inv, "document")
    parts = []
    extracted = None
    if input_ and input_.get("filePath"):
        extracted = read_stored_text(input_["filePath"])
        if not extracted:
            f = read_stored_file_base64(input_["filePath"])
            if f:
                parts.append({"file": f})
    if extracted:
        parts.append({"text": f"DOCUMENT_TEXT:\n{extracted}"})
    elif not any(p.get("file") for p in parts):
        parts.append({"text": f"DOCUMENT_CONTEXT: {input_.get('content') if input_ else _first_text_input(inv) or ''}"})
    return await _run_analysis(inv, evidence, system_prompt, parts)


async def _source_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's web source credibility analyst. Evaluate the submitted URL using the live web inspection data (DNS, SSL, HTTP, content snippet) "
        "and the acquired evidence. Assess credibility signals, not absolute verification. Express confidence honestly. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    url_input = _find_input(inv, "url")
    inspection = inv.get("webInspection")
    context = [
        f"URL: {url_input.get('content') if url_input else _first_text_input(inv) or inv.get('question')}",
        f"LIVE_WEB_INSPECTION:\n{json_dumps(inspection)}" if inspection else "No live web inspection was performed.",
    ]
    return await _run_analysis(inv, evidence, system_prompt, [{"text": "\n\n".join(context)}])


async def _data_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's structured-data analyst. Inspect the submitted CSV/JSON dataset for anomalies, inconsistencies, missing values, or suspicious patterns, "
        "together with acquired evidence. Express confidence honestly. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    input_ = _find_input(inv, "data") or _find_input(inv, "text")
    content = None
    if input_ and input_.get("filePath"):
        content = read_stored_text(input_["filePath"], 30000)
    data_context = content or (input_.get("content") if input_ else None) or inv.get("question")
    return await _run_analysis(inv, evidence, system_prompt, [{"text": f"DATA_CONTEXT:\n{data_context}"}])


def json_dumps(obj):
    import json
    try:
        return json.dumps(obj, indent=2)
    except Exception:
        return str(obj)


register_analyzer("claim-investigation", _claim_analyzer)
register_analyzer("image-investigation", _image_analyzer)
register_analyzer("video-investigation", _video_analyzer)
register_analyzer("document-investigation", _document_analyzer)
register_analyzer("source-investigation", _source_analyzer)
register_analyzer("data-investigation", _data_analyzer)