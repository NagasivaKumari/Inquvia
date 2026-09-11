"""Capability analyzer registry (mirrors investigation/analyzers.ts)."""
from ..libraries import storage, ai as ai_lib, signals as signals_lib, document_extract
from ..libraries.analyze import (
    heuristic_analysis,
    redundant_evidence_ids,
    clamp_confidence,
    normalize_conclusion,
    VALID_RISKS,
    read_stored_text,
    read_stored_file_base64,
    run_ai_ocr,
)

REGISTRY = {}


_QUESTION_RULE = (
    "Match your conclusion to the user's actual question. If the question is to extract, list, summarize, "
    "transcribe, or describe content, DO NOT issue an authenticity/manipulation verdict: report the extracted "
    "content in findings and use conclusion 'inconclusive' with confidence reflecting the reliability of the "
    "facts you extracted. If the question asks whether content is genuine, manipulated, fake, or risky, issue a "
    "verdict ONLY when observable file-level or extracted signals support it; never allege manipulation without "
    "evidence, and state the evidence and limitations each time. Set confidence relative to the question actually "
    "being answered, and be explicit about uncertainty. "
)


def register_analyzer(capability_id, fn):
    REGISTRY[capability_id] = fn


def get_analyzer(capability_id):
    return REGISTRY.get(capability_id) if capability_id else None


def _to_str_array(v) -> list[str]:
    if not isinstance(v, list):
        return []
    return [s[:500] for s in v if isinstance(s, str)]


def _apply_evidence_signals(evidence: list[dict], signals) -> None:
    """Stamp per-evidence signals returned by the model onto the evidence
    items (in place), so supporting/contradictory tallies and the evidence
    graph reflect the analysis verdict instead of staying 'uncertain'."""
    if not signals:
        return
    by_id = {
        s.get("id"): s.get("signal")
        for s in signals
        if isinstance(s, dict) and isinstance(s.get("id"), str)
    }
    valid = {"supporting", "contradictory", "uncertain"}
    for e in evidence:
        sig = by_id.get(e.get("id"))
        if sig in valid:
            e["signal"] = sig


def _merge_ai_raw(inv, evidence, raw) -> dict:
    _apply_evidence_signals(evidence, (raw or {}).get("evidenceSignals"))
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
    if isinstance(conclusion_text_raw, str) and conclusion_text_raw and conclusion_text_raw != base["conclusionText"]:
        conclusion_text = conclusion_text_raw
    elif raw.get("answer"):
        conclusion_text = f"Answer: {raw['answer']}".strip()
    elif findings or conclusion != base["conclusion"]:
        summary = " ".join(findings[:1]) or conclusion.replace("_", " ").upper()
        conclusion_text = f"Assessment: {conclusion.replace('_', ' ').upper()}. {summary}".strip()
    else:
        conclusion_text = base["conclusionText"]
    if not conclusion_text:
        conclusion_text = (
            f"Assessment: {conclusion.replace('_', ' ').upper()}. "
            f"{' '.join(limitations) if limitations else ''}"
        ).strip()
    result = {
        "conclusion": conclusion,
        "conclusionText": conclusion_text,
        "confidence": confidence,
        "risk": risk,
        "findings": findings,
        "contradictions": contradictions if contradictions else base["contradictions"],
        "limitations": limitations if limitations else base["limitations"],
        "uncertainty": uncertainty,
        "sourcesUsed": sources_used,
        "evidenceRelationships": base.get("evidenceRelationships") or {
            "supporting": 0, "contradicting": 0, "established": False,
        },
    }
    # Question-relevant structured document result: the answer to the user's
    # question, the reasoning, the selected passages (with provenance), and
    # explicit gaps. Passed through so the engine can persist them.
    for key in (
        "answer",
        "assessmentReasoning",
        "evidenceItems",
        "missingInformation",
        "additionalSourcesNeeded",
    ):
        if raw.get(key) not in (None, "", []):
            result[key] = raw.get(key)
    return result


async def _run_analysis(inv, evidence, system_prompt, context_parts) -> dict:
    # Reason only over non-redundant evidence: duplicate/dependent copies
    # (provider-flagged) stay in the trail but must not be fed as if they were
    # extra independent confirmations.
    effective = [e for e in evidence if e["id"] not in redundant_evidence_ids(inv, evidence)]
    if effective:
        evidence_text = "\n".join(
            f"{i + 1}. [{e.get('signal')}] source={e.get('source')} finding={e.get('finding')} confidence={e.get('confidence')}"
            for i, e in enumerate(effective)
        )
        system_prompt += (
            "\nFor each acquired evidence item you used, also return 'evidenceSignals': "
            "[{'id': <evidence id>, 'signal': 'supporting'|'contradictory'|'uncertain'}]. "
            "Classify each item honestly; items that neither support nor contradict the claim are 'uncertain'."
        )
    elif evidence:
        # Do not let a model manufacture a conclusion from copied or dependent
        # evidence. Keep the acquired items in the trail and report insufficiency.
        return heuristic_analysis(inv, evidence)
    else:
        # Internal capability analysis is allowed to reason over the user's
        # submitted input without buying evidence from another service.
        evidence_text = "No external evidence was acquired. Analyze only the submitted input and state limitations clearly."
    context_parts.append({"text": f"QUESTION: {inv.get('question')}\n\nACQUIRED EVIDENCE:\n{evidence_text}"})
    raw_text = await ai_lib.call_ai_with_parts(system_prompt, context_parts)
    raw = ai_lib.parse_ai_json(raw_text)
    return _merge_ai_raw(inv, evidence, raw)


def _first_text_input(inv):
    for i in inv.get("inputs") or []:
        t = i.get("type")
        if t in ("text", "url"):
            return i.get("content")
        if t in ("document", "data"):
            text = read_stored_text(i["filePath"]) if i.get("filePath") else None
            if text:
                return text
    return None


def _find_input(inv, input_type):
    for i in inv.get("inputs") or []:
        if i.get("type") == input_type:
            return i
    return None


async def _claim_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's claim verification analyst. Assess whether the submitted claim is supported, contradicted, or unresolved, "
        "using the submitted input and any acquired evidence. Do not use internal knowledge to fill evidence gaps. Be explicit about uncertainty. Do not claim a conclusion you cannot support. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    claim = _first_text_input(inv) or inv.get("question")
    parts = [{"text": f"CLAIM: {claim}"}]
    # Read content from any submitted file inputs (document, data, audio, etc.)
    # so the AI can reason over the actual submitted content, not just the question.
    for inp in inv.get("inputs") or []:
        if inp.get("filePath"):
            extracted = read_stored_text(inp["filePath"])
            if extracted:
                label = inp.get("content") or inp.get("fileName") or "file"
                parts.append({"text": f"SUBMITTED_DOCUMENT ({label}):\n{extracted}"})
            else:
                f = read_stored_file_base64(inp["filePath"])
                if f:
                    parts.append({"file": f})
    return await _run_analysis(inv, evidence, system_prompt, parts)


async def _image_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's image forensics analyst. Inspect the provided image(s) for signs of manipulation, "
        "generative-AI artifacts, or provenance inconsistencies, together with the acquired evidence and the "
        "extracted FILE_LEVEL_SIGNALS (metadata, format, dimensions, editor tags). "
        "When multiple images are provided, compare them against each other for provenance and editing differences. "
        "Do not claim verified authenticity. Base every conclusion on observable, defensible signals; do not "
        "claim metadata or file-level facts beyond what FILE_LEVEL_SIGNALS states. State evidence and limitations explicitly. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    images = [i for i in (inv.get("inputs") or []) if i.get("type") == "image"]
    parts = []
    for input_ in images:
        if input_.get("filePath"):
            f = read_stored_file_base64(input_["filePath"])
            if f:
                parts.append({"file": f})
                label = input_.get("content") or input_.get("fileName") or "image"
                parts.append({"text": f"IMAGE_CONTEXT: {label}"})
                sig_text = signals_lib.inspect_text(input_["filePath"], "image")
                if sig_text:
                    parts.append({"text": sig_text})
    if not any(p.get("file") for p in parts):
        context = _first_text_input(inv) or ""
        if context:
            parts.append({"text": f"IMAGE_CONTEXT: {context}"})
    if len(images) > 1:
        parts.append({"text": f"NOTE: {len(images)} images were submitted — compare them against each other."})
    return await _run_analysis(inv, evidence, system_prompt, parts)


async def _video_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's video forensics analyst. Assess the submitted video(s) using the extracted "
        "FILE_LEVEL_SIGNALS (container, brands, track dimensions, duration) and the visible frame content, "
        "together with the acquired evidence. Identify only defensible forensic or file-level signals such as "
        "metadata, recompression, frame inconsistencies, encoding anomalies, or other observable irregularities. "
        "Do not claim that the video is AI-generated, manipulated, or authentic unless the evidence supports that "
        "conclusion; clearly state the evidence and limitations. When multiple videos are provided, compare them against each other. "
        "Express confidence honestly; explicit uncertainty is expected. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    videos = [i for i in (inv.get("inputs") or []) if i.get("type") == "video"]
    parts = []
    for input_ in videos:
        if input_.get("filePath"):
            f = read_stored_file_base64(input_["filePath"])
            if f:
                parts.append({"file": f})
                label = input_.get("content") or input_.get("fileName") or "video"
                parts.append({"text": f"VIDEO_CONTEXT: {label}"})
                sig_text = signals_lib.inspect_text(input_["filePath"], "video")
                if sig_text:
                    parts.append({"text": sig_text})
    if not any(p.get("file") for p in parts):
        context = _first_text_input(inv) or ""
        if context:
            parts.append({"text": f"VIDEO_CONTEXT: {context}"})
    if len(videos) > 1:
        parts.append({"text": f"NOTE: {len(videos)} videos were submitted — compare them against each other."})
    return await _run_analysis(inv, evidence, system_prompt, parts)


_DOCUMENT_RULES = (
    "The user's actual investigation question below is the PRIMARY objective of this analysis. "
    "Answer THAT question using the provided document and acquired evidence. Do not produce a generic "
    "document summary; every finding and the final answer must relate to the user's question. "
    "If the document does not contain enough evidence to answer it, say so honestly (missingInformation) and "
    "end with conclusion 'insufficient_evidence' or 'inconclusive'. Never manufacture evidence merely because "
    "a question was asked. "
    "Search the ENTIRE document, not just the first matching passage: for numerical, date, identity, factual, "
    "or timeline questions, locate and compare ALL relevant occurrences and reconcile inconsistencies between "
    "them instead of relying on the first match. "
    "For each passage you rely on, return its exact text (quote), page number, any section/table/paragraph "
    "available, and its provenance (source: 'text_layer' for selectable text, 'ocr' for scanned pages read "
    "from the rendered image — never invent a source). "
    "Classify the nature of each passage: 'stated_fact' (the document directly asserts a fact), "
    "'document_claim' (the document itself makes/asserts a claim, distinct from established fact), "
    "'observation' (something the document records or reports), 'interpretation' (your inference drawn from "
    "the text), 'uncertain' (the text is ambiguous), or 'missing' (the document lacks this; see missingInformation). "
    "Mark each passage's relationship to the question as 'supporting', 'contradictory', or 'unestablished'. "
    "If neither supporting nor contradictory evidence is established, represent that accurately; do not force "
    "a verdict. "
    "For authenticity/verification questions: distinguish evidence contained in the document itself from "
    "independent authentication — never claim authenticity merely because the document looks official. "
    "If the question can only be answered with information the document cannot provide, identify in "
    "additionalSourcesNeeded what other evidence/source would be required, and do not silently use another source. "
)

_DOCUMENT_JSON_SCHEMA = (
    "{ conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
    "confidence: number 0-100, "
    "answer: string (your final answer to the USER'S question, or an explicit insufficiency statement), "
    "assessmentReasoning: string (explain why the available evidence supports, weakens, contradicts, or fails "
    "to establish the user's claim), "
    "evidenceItems: [ { quote: string, page: number|null, section: string|null, table: string|null, "
    "paragraph: string|null, source: 'text_layer'|'ocr'|'plain_text', "
    "nature: 'stated_fact'|'document_claim'|'observation'|'interpretation'|'uncertain'|'missing', "
    "relationship: 'supporting'|'contradictory'|'unestablished', rationale: string } ], "
    "contradictions: string[] (exact conflicting passages with their locations), "
    "findings: string[], limitations: string[], "
    "missingInformation: string[] (exactly what is absent from the document), "
    "additionalSourcesNeeded: string[], uncertainty: string, sourcesUsed: string[], "
    "risk: 'low'|'moderate'|'high'|'unknown' }"
)


def _page_text_block(pages: list[dict], max_chars: int = 150000) -> str:
    """Render numbered pages with provenance labels, bounded for the model."""
    # ponytail: fixed context cap; chunk/retrieve when documents routinely
    # exceed the model context window.
    block = []
    total = 0
    for p in pages:
        label = p.get("source") or "text_layer"
        text = p.get("text")
        if text:
            chunk = f"[PAGE {p['page']}] (source: {label})\n{text}"
        else:
            chunk = f"[PAGE {p['page']}] (source: {label})\n(no readable text recovered from this page)"
        if total + len(chunk) > max_chars:
            block.append(f"[PAGE {p['page']}] (source: {label})\n[text truncated for model context]")
            break
        block.append(chunk)
        total += len(chunk)
    return "\n\n".join(block)


async def _load_document_pages(inv, input_: dict | None) -> list[dict]:
    """Full page extraction for the analyzer: prefers the extraction cached by
    the document_verify evidence check; falls back to fresh extraction with OCR."""
    if input_:
        cached = input_.get("documentExtraction") or {}
        pages = cached.get("pages")
        if pages:
            return pages
        if input_.get("filePath"):
            data = signals_lib.load_bytes(input_["filePath"])
            if data:
                extracted = await document_extract.extract_document_pages_with_ocr(
                    data, input_.get("mimeType"), run_ai_ocr
                )
                if extracted:
                    input_["documentExtraction"] = extracted
                    return extracted["pages"]
    return []


async def _run_document_analysis(inv, evidence, system_prompt, context_parts) -> dict:
    """Document-specific reasoning loop: the full page structure is the primary
    evidence body (comprehensive extraction), the user's question is the sole
    objective, and page provenance is preserved in the model output."""
    effective = [e for e in evidence if e["id"] not in redundant_evidence_ids(inv, evidence)]
    if effective:
        evidence_text = "\n".join(
            f"{i + 1}. [{e.get('signal')}] source={e.get('source')} finding={e.get('finding')} confidence={e.get('confidence')}"
            for i, e in enumerate(effective)
        )
        system_prompt += (
            "\nFor each acquired evidence item you used, also return 'evidenceSignals': "
            "[{'id': <evidence id>, 'signal': 'supporting'|'contradictory'|'uncertain'}]. "
            "Classify each item honestly; items that neither support nor contradict the question are 'uncertain'."
        )
    elif evidence:
        return heuristic_analysis(inv, evidence)
    else:
        evidence_text = "No external evidence was acquired. Analyze only the submitted document and state limitations clearly."
    context_parts.append({
        "text": f"INVESTIGATION_OBJECTIVE (the user's question — your sole objective): {inv.get('question')}\n\n"
                f"ACQUIRED EVIDENCE:\n{evidence_text}"
    })
    raw_text = await ai_lib.call_ai_with_parts(system_prompt, context_parts)
    raw = ai_lib.parse_ai_json(raw_text) or {}
    result = _merge_ai_raw(inv, evidence, raw)
    # The document's relationship summary comes from the SELECTED passages, not
    # from counting every page record. Zero on both sides = no relationship was
    # established, represented accurately (never forced).
    items = [i for i in (raw.get("evidenceItems") or []) if isinstance(i, dict)]
    supporting = [i for i in items if i.get("relationship") == "supporting"]
    contradicting = [i for i in items if i.get("relationship") == "contradictory"]
    if items:
        result["evidenceRelationships"] = {
            "supporting": len(supporting),
            "contradicting": len(contradicting),
            "established": bool(supporting or contradicting),
        }
    return result


async def _document_analyzer(inv, evidence):
    input_ = _find_input(inv, "document")
    pages = await _load_document_pages(inv, input_)
    if not pages:
        # No readable document content → honest insufficiency, never fabricated.
        return heuristic_analysis(inv, evidence)

    extraction_source = (input_.get("documentExtraction") or {}).get("extractionSource") or "mixed"
    page_block = _page_text_block(pages)

    system_prompt = (
        _QUESTION_RULE +
        _DOCUMENT_RULES +
        "You are Inquvia's document evidence analyst. " +
        f"Return ONLY JSON with this exact schema:\n{_DOCUMENT_JSON_SCHEMA}"
    )
    parts = [{"text": page_block}]
    if input_:
        parts.append({"text": f"DOCUMENT: {input_.get('content') or input_.get('fileName') or 'submitted document'} "
                             f"(extraction: {extraction_source}, {len(pages)} page(s))"})
    return await _run_document_analysis(inv, evidence, system_prompt, parts)


async def _source_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
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
    system_prompt = _QUESTION_RULE + (
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


async def _audio_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's audio forensics analyst. PRIORITIZE extracting a full transcript if possible from the provided content, or at least a detailed summary of spoken content. Assess the submitted audio recording(s) using the extracted FILE_LEVEL_SIGNALS (container, sample rate, channels, bit depth, duration) and any audible content, together with the acquired evidence. Base conclusions only on defensible, observable signals; do not claim splicing, cloning, or manipulation unless the evidence supports it. State evidence and limitations explicitly. "
        "When multiple recordings are provided, compare them against each other. "
        "Express confidence honestly; explicit uncertainty is expected. "
        "Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, transcript: string, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }."
    )
    audios = [i for i in (inv.get("inputs") or []) if i.get("type") == "audio"]
    parts = []
    for input_ in audios:
        if input_.get("filePath"):
            f = read_stored_file_base64(input_["filePath"])
            if f:
                parts.append({"file": f})
                label = input_.get("content") or input_.get("fileName") or "audio"
                parts.append({"text": f"AUDIO_CONTEXT: {label}"})
                sig_text = signals_lib.inspect_text(input_["filePath"], "audio")
                if sig_text:
                    parts.append({"text": sig_text})
    if not any(p.get("file") for p in parts):
        context = _first_text_input(inv) or ""
        if context:
            parts.append({"text": f"AUDIO_CONTEXT: {context}"})
    if len(audios) > 1:
        parts.append({"text": f"NOTE: {len(audios)} audio recordings were submitted — compare them against each other."})
    return await _run_analysis(inv, evidence, system_prompt, parts)


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
register_analyzer("audio-investigation", _audio_analyzer)