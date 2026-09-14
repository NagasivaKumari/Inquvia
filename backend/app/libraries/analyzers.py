"""Capability analyzer registry (mirrors investigation/analyzers.ts)."""
import base64
import secrets
from datetime import datetime, timezone

from ..libraries import storage, ai as ai_lib, signals as signals_lib, document_extract
from ..libraries import compute_structured
from ..libraries.video_processor import (
    VideoProcessor,
    frame_payload_bytes,
    prepare_video,
)
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
from ..libraries import image_investigation_helpers as img_inv_helpers

REGISTRY = {}


# Shared question-driven reasoning rule -- the user's exact question is the PRIMARY objective.
# If the question asks to EXTRACT, TRANSCRIBE, DESCRIBE, SUMMARIZE, or LIST content:
#   - Provide a direct answer in the 'answer' field.
#   - Use conclusion 'answered' if fully answered, 'inconclusive' if partial,
#     'insufficient_evidence' if the content cannot answer it.
# If the question asks whether content is GENUINE, MANIPULATED, FAKE, AI-GENERATED, or RISKY:
#   - Issue a forensic verdict ONLY when observable signals support it.
#   - Use conclusion 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'.
# If the question asks WHETHER A CLAIM IS SUPPORTED: assess the claim against the evidence.
# In ALL cases: cite evidence, state limitations, express confidence honestly (0-100).
_QUESTION_RULE = (
    "The user's exact question is the PRIMARY objective. "
    "If the question asks to EXTRACT, TRANSCRIBE, DESCRIBE, SUMMARIZE, or LIST content: "
    "provide a direct answer in the 'answer' field. Use conclusion 'answered' if the question "
    "is fully answered, 'inconclusive' if only partially answered, or 'insufficient_evidence' "
    "if the content cannot answer it. "
    "If the question asks whether content is GENUINE, MANIPULATED, FAKE, AI-GENERATED, or RISKY: "
    "issue a forensic verdict ONLY when observable signals support it. "
    "Use conclusion 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'. "
    "If the question asks WHETHER A CLAIM IS SUPPORTED: assess the claim against the evidence. "
    "In ALL cases: cite evidence, state limitations, express confidence honestly (0-100). "
    "Return an 'answer' field for extraction/description questions; 'assessmentReasoning' for verification questions. "
    "Valid conclusions: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive'. "
    "Express uncertainty explicitly. "
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
    graph reflect the analysis verdict instead of staying 'uncertain'.

    A 'supporting' signal set by a deterministic check (e.g. successful URL
    retrieval) is the floor: the AI can upgrade uncertain→supporting or
    uncertain→contradictory, but must not downgrade supporting→uncertain.
    This prevents the AI from mislabeling a successful retrieval as uncertain
    merely because the answer to the question is uncertain.
    
    An 'observed' signal (file-level metadata observation) is kept as-is: the
    observation is a fact, not an interpretation. The AI cannot change it."""
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
        if sig not in valid:
            continue
        current = e.get("signal")
        # Never downgrade a deterministic 'supporting' signal to 'uncertain'.
        # The check set 'supporting' because retrieval succeeded; that fact
        # does not change based on whether the AI can answer the question.
        if current == "supporting" and sig == "uncertain":
            continue
        # Never change an 'observed' signal (file-level metadata observation).
        # Observed facts remain observed regardless of their relevance to the answer.
        if current == "observed":
            continue
        e["signal"] = sig


def _merge_ai_raw(inv, evidence, raw) -> dict:
    _apply_evidence_signals(evidence, (raw or {}).get("evidenceSignals"))
    base = heuristic_analysis(inv, evidence)
    if not raw:
        return base
    conclusion = normalize_conclusion(raw.get("conclusion")) or base["conclusion"]
    raw_conf = raw.get("confidence")
    conf_value = None
    if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool):
        conf_value = float(raw_conf)
    elif isinstance(raw_conf, str):
        try:
            conf_value = float(raw_conf)
        except ValueError:
            pass
    confidence = base["confidence"]
    if conf_value is not None:
        confidence = clamp_confidence(conf_value)
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
    # evidenceRelationships is recomputed from the post-signal-update heuristic
    # so it reflects any signal changes applied by _apply_evidence_signals above.
    ev_rel = base.get("evidenceRelationships") or {
        "supporting": 0, "contradicting": 0, "established": False,
    }
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
        "evidenceRelationships": ev_rel,
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
        "objectCounts",
        "mediaAuthenticity",
        "contextualAccuracy",
        "subObjectives",
        "provenance",
        "observedDirectly",
        "externallyVerified",
        "inferred",
        "couldNotVerify",
        "forensicFindings",
        "investigationTrace",
        "externalEvidence",
        "evidenceAssessment",
    ):
        if raw.get(key) not in (None, "", []):
            result[key] = raw.get(key)
    return result


async def _run_analysis(inv, evidence, system_prompt, context_parts, text_fallback: bool = True) -> dict:
    # Reason only over non-redundant evidence: duplicate/dependent copies
    # (provider-flagged) stay in the trail but must not be fed as if they were
    # extra independent confirmations.
    effective = [e for e in evidence if e["id"] not in redundant_evidence_ids(inv, evidence)]
    if effective:
        evidence_text = "\n".join(
            f"{i + 1}. [id={e.get('id')} signal={e.get('signal')}] source={e.get('source')} finding={e.get('finding')} confidence={e.get('confidence')}"
            for i, e in enumerate(effective)
        )
        system_prompt += (
            "\nFor each acquired evidence item you used, also return 'evidenceSignals': "
            "[{'id': <evidence id>, 'signal': 'supporting'|'contradictory'|'uncertain'}]. "
            "Use the exact id values shown in the ACQUIRED EVIDENCE list. "
            "Classify each item honestly: 'supporting' if it contains content that answers "
            "or supports the claim, 'contradictory' if it conflicts, 'uncertain' only if it "
            "genuinely neither supports nor contradicts. "
            "A successful page retrieval containing the answer MUST be 'supporting'."
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
    raw_text = await ai_lib.call_ai_with_parts(system_prompt, context_parts, text_fallback=text_fallback)
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
        "You are Inquvia's claim analyst. Assess whether the submitted claim is supported, contradicted, or unresolved, "
        "using the submitted input and any acquired evidence. Do not use internal knowledge to fill evidence gaps. "
        "Be explicit about uncertainty. Do not claim a conclusion you cannot support. "
        "If the question asks to extract, summarize, or describe the claim: provide the extracted content in 'answer' "
        "and use conclusion 'answered'. If the question asks whether the claim is true/supported: issue a forensic "
        "verdict ONLY when observable signals support it. "
        "Return ONLY JSON: { conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
        "confidence: number 0-100, answer: string, assessmentReasoning: string, "
        "findings: string[], contradictions: string[], limitations: string[], uncertainty: string, "
        "sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', "
        "evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }."
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
    return await _run_analysis(inv, evidence, system_prompt, parts, text_fallback=False)


# Evidence grounding rules for image investigations — generic, question-independent.
_IMAGE_EVIDENCE_RULES = (
    "EVIDENCE GROUNDING RULES:\n"
    "1. OBSERVATION vs INFERENCE vs EXTERNAL REQUIREMENT:\n"
    "   - Directly observable (high confidence): color, shape, visible objects, readable text, "
    "apparent texture, visible composition, spatial relationships, visible labels/markings.\n"
    "   - Inferred (moderate confidence, must be labeled 'appears to' / 'suggests'): "
    "material composition, manufacturing technique, approximate age, emotional state.\n"
    "   - Requires external evidence (low/no confidence from image alone): brand identity, "
    "designer attribution, originality, copyright ownership, provenance, identity of persons, "
    "authenticity, prior publication history.\n"
    "2. EVIDENCE HIERARCHY: Use only levels 1-3 as factual conclusions:\n"
    "   Level 1 = directly observed. Level 2 = extracted (metadata). "
    "Level 3 = evidence-supported inference. Level 4 = unverified hypothesis (label explicitly). "
    "Level 5 = unsupported claim (do NOT present as answer).\n"
    "3. NO INVENTED FACTS: Do not convert visual resemblance into factual identity. "
    "Do not convert appearance into material composition. "
    "Do not convert similarity into originality/copying. "
    "Do not infer provenance without provenance evidence. "
    "Do not infer a person's identity without appropriate evidence.\n"
    "4. METADATA SEMANTICS: File-level metadata (format, dimensions, EXIF) is separate from "
    "visual evidence. Metadata presence does not establish originality or authenticity.\n"
    "5. EVIDENCE SIGNALS: Assign 'supporting' to evidence that directly supports a claim in "
    "your answer. Assign 'contradictory' if it conflicts. Assign 'uncertain' ONLY if it "
    "genuinely neither supports nor contradicts. File-level metadata confirming observable "
    "properties MUST be 'supporting', not 'uncertain'.\n"
    "6. CONFIDENCE CALIBRATION:\n"
    "   - 80-95: directly observable facts with clear visual evidence.\n"
    "   - 50-75: inferences with visible supporting detail.\n"
    "   - 20-49: claims requiring external evidence that was not acquired.\n"
    "   - 0-19: claims that cannot be established from the image at all.\n"
    "   For multi-part questions, overall confidence = confidence of the weakest sub-objective.\n"
    "7. CONCLUSION SEMANTICS:\n"
    "   - 'answered': evidence supports a direct answer to the question.\n"
    "   - 'inconclusive': evidence is conflicting or does not establish a reliable conclusion.\n"
    "   - 'insufficient_evidence': required evidence cannot be obtained from the image.\n"
    "   - 'likely_genuine'/'likely_misleading'/'suspicious': forensic verdicts only when "
    "observable signals support them.\n"
    "   Do NOT use 'uncertain' as a generic fallback. Do NOT force every investigation into 'answered'.\n"
    "8. CROSS-CHECK: Before returning your answer, verify every factual statement against the "
    "evidence. Remove or qualify any statement not traceable to acquired evidence.\n"
    "9. EXTERNAL EVIDENCE HONESTY: If reverse-image or authoritative web search evidence says "
    "'not provisioned', 'no matches', or 'no results', you MUST NOT claim that external sources "
    "were verified, cross-checked, or consulted. Say explicitly: 'No independent external "
    "evidence was acquired.' Never write 'no material contradictions across verified sources' "
    "when no external sources were acquired.\n"
    "10. MISSING METADATA IS NOT FAKE: Absent EXIF/GPS/editor tags is common after social-media "
    "uploads and is NOT evidence of forgery. State it as a fact, not an authenticity signal.\n"
    "11. IMAGE vs CONTEXT: A genuine file can carry a false caption. Report mediaAuthenticity "
    "and contextualAccuracy separately.\n"
)

# Generic object-counting / distinct-object rules for image questions. These
# are deliberately category-agnostic: no specific object or category names, no
# quantities, no filenames, no expected answers.
_IMAGE_COUNTING_RULES = (
    "OBJECT COUNTING RULES (apply whenever the question asks HOW MANY, or requires counting "
    "a category of physical objects visible in the image):\n"
    "1. ENUMERATE BEFORE COUNTING: for each requested category, identify every distinct physical "
    "instance and list it as its own entry with a short label and a location description derived "
    "from the image (e.g. 'left of the doorway', 'top-right corner', 'behind the desk'). Compute "
    "the count only from that list of instances.\n"
    "2. ONE OBJECT = ONE INSTANCE: count distinct physical objects, not visible fragments. When "
    "two visible parts clearly belong to one continuous object (adjacent positions, matching "
    "appearance, aligned edges, connected shapes), they are a single instance. Do not double-count "
    "one object seen from multiple angles or protruding from behind cover.\n"
    "3. PARTIAL VISIBILITY COUNTS: a partially visible object — cropped at the frame edge, mostly "
    "hidden behind another object, or partly out of view — is still a distinct instance when the "
    "visible portion is sufficient to identify it as the category and shows it is separate from "
    "its neighbours. Mark it 'partially_visible'. Do not treat every visible sliver as a separate "
    "object.\n"
    "4. REPRESENTATIONS ARE NOT PHYSICAL INSTANCES: an object shown inside a screen, monitor, "
    "photograph, poster, painting, sign, label, or printed text is a representation of the object, "
    "not a physical instance present in the scene. Exclude such representations from physical "
    "counts. A physical object and its reflection or mirror image are the same single object — "
    "count the physical instance once.\n"
    "5. COUNT MUST MATCH THE ENUMERATION: the number reported in your answer must equal the number "
    "of instances you listed. Re-read the instance list and reconcile your answer against it; the "
    "instance list is the source of truth.\n"
    "6. UNRESOLVABLE COUNTS: if objects are so heavily occluded or ambiguous that the exact number "
    "cannot be established (e.g. a continuous mass where one object ends and another begins), do "
    "NOT invent a precise number. Report the range you can defend, set countCertain=false, and "
    "state in 'uncertainty' and 'limitations' exactly which instances could not be resolved and why.\n"
)


def _reconcile_object_counts(raw: dict) -> tuple[list | None, list[str]]:
    """Deterministic cross-check for object category counts.

    The individually enumerated instances are the source of truth: a reported
    category count is corrected to equal the number of listed instances, and a
    count asserted without any instance list is marked unverifiable instead of
    being passed through as fact.
    """
    raw_counts = raw.get("objectCounts")
    if not isinstance(raw_counts, list):
        return None, []
    counts, notes = [], []
    for i, entry in enumerate(raw_counts):
        if not isinstance(entry, dict):
            continue
        entry = dict(entry)
        inst = [x for x in (entry.get("instances") or []) if isinstance(x, dict)]
        entry["instances"] = inst
        label = entry.get("category") or f"entry {i + 1}"
        if inst:
            enumerated = len(inst)
            claimed = entry.get("count")
            entry["count"] = enumerated
            if claimed not in (None, "", enumerated):
                notes.append(
                    f"Object category '{label}': the reported count did not match the enumerated "
                    f"instances and was corrected to {enumerated}."
                )
        else:
            claimed = entry.get("count")
            if claimed in (None, 0, "0"):
                entry["count"] = 0
            else:
                entry["count"] = None
                entry["countCertain"] = False
                notes.append(
                    f"Object category '{label}': a count was reported without an enumerated "
                    "instance list, so it could not be verified against the image observations."
                )
        entry.setdefault("countCertain", bool(inst))
        counts.append(entry)
    return counts, notes


async def _image_analyzer(inv, evidence):
    """Open-ended image investigator.

    The user's question drives everything: sub-objectives are decomposed from
    the question, evidence is evaluated per sub-objective, and the final answer
    is cross-checked against the evidence before returning.
    """
    from ..libraries import image_medical

    medical_block = ""
    if inv.get("medicalInvestigation") or image_medical.is_medical_question(inv.get("question") or ""):
        medical_block = (
            image_medical.MEDICAL_DISCLAIMER + "\n"
            "Do NOT provide medical diagnosis. Limit findings to generic file/visual observations.\n\n"
        )
    system_prompt = (
        _QUESTION_RULE + _IMAGE_EVIDENCE_RULES + _IMAGE_COUNTING_RULES + medical_block +
        "You are Inquvia's image analyst. Answer the user's question by analyzing the provided "
        "image(s) and any acquired evidence. Apply the EVIDENCE GROUNDING RULES strictly.\n\n"
        "PROCESS (follow in order):\n"
        "1. DECOMPOSE: Read the user's question and identify every sub-objective "
        "(what must be established to fully answer it).\n"
        "2. CLASSIFY each sub-objective as:\n"
        "   a) Answerable from direct visual observation\n"
        "   b) Answerable by inference from visual evidence (label as inference)\n"
        "   c) Requires external evidence not available from the image alone\n"
        "3. EVIDENCE-DRIVEN ANALYSIS (use ONLY checks found in ACQUIRED EVIDENCE):\n"
        "   - METADATA: ('Image metadata' evidence).\n"
        "   - FORENSICS: ('Image manipulation', 'AI-generation detection' evidence). Report observed numbers.\n"
        "   - PROVENANCE/SEARCH: ('Reverse-image search', 'Authoritative web source search' evidence). Use for earliest-source dating and context verification.\n"
        "   - SPECIALIZED: ('Privacy/Safety', 'Commercial', 'Document', 'Scientific', 'Geospatial' evidence).\n"
        "4. ANSWER each sub-objective independently using the appropriate evidence level.\n"
        "5. If any sub-objective requires counting a category of objects, run the OBJECT COUNTING RULES and record in 'objectCounts'.\n"
        "6. CROSS-CHECK: Verify every factual statement in your answer against the evidence. Detect unsupported statements and remove or qualify them.\n"
        "7. SYNTHESIZE: Combine sub-objective results into a coherent overall answer.\n"
        "8. DISTINGUISH VERDICTS: Distinguish 'Media Authenticity' (file genuineness) from 'Contextual Accuracy' (content truthfulness). If external sources were NOT acquired, explicitly state: 'No independent external evidence was acquired. This assessment is limited to the submitted image and internal file analysis.'\n"
        "9. ASSIGN evidenceSignals for each acquired evidence item based on what it actually supports.\n"
        "10. SET confidence to reflect the weakest sub-objective.\n\n"
        "Return ONLY JSON with this exact schema:\n"
        "{ conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
        "confidence: number 0-100, "
        "answer: string, assessmentReasoning: string, "
        "mediaAuthenticity: {verdict: 'authentic'|'manipulated'|'ai_generated'|'unknown', reasoning: string}, "
        "contextualAccuracy: {verdict: 'accurate'|'misleading'|'false'|'unknown', reasoning: string}, "
        "forensicFindings: {visualObservations: string[], externallyVerifiedFacts: string[], inferences: string[], couldNotVerify: string[], contradictions: string[]}, "
        "subObjectives: [{objective: string, status: 'answered'|'inconclusive'|'insufficient_evidence', evidenceLevel: 'observed'|'inferred'|'external_required', finding: string}], "
        "objectCounts: [{category: string, count: number|null, countCertain: boolean, instances: [{id: string, description: string, location: string, visibility: 'fully_visible'|'partially_visible'}], uncertainty: string}], "
        "limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', "
        "evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }"
    )
    images = [i for i in (inv.get("inputs") or []) if i.get("type") == "image"]
    parts = []
    missing_images = []
    for input_ in images:
        if input_.get("filePath"):
            f = read_stored_file_base64(input_["filePath"])
            if f:
                parts.append({"file": {"mimeType": f.get("mimeType") or input_.get("mimeType") or "image/jpeg", "base64": f.get("base64")}})
                label = input_.get("content") or input_.get("fileName") or "image"
                parts.append({"text": f"IMAGE_CONTEXT: {label}"})
                sig_text = signals_lib.inspect_text(input_["filePath"], "image")
                if sig_text:
                    parts.append({"text": sig_text})
            else:
                missing_images.append(input_.get("fileName") or input_.get("content") or "image")
    if missing_images:
        return {
            "conclusion": "insufficient_evidence",
            "confidence": 0,
            "answer": f"Unable to analyze image content: the following image file(s) could not be accessed from storage: {', '.join(missing_images)}",
            "assessmentReasoning": "Visual analysis requires direct access to the submitted image bytes. File retrieval from storage failed, so no visual observations could be made.",
            "mediaAuthenticity": {"verdict": "unknown", "reasoning": "Could not access image."},
            "contextualAccuracy": {"verdict": "unknown", "reasoning": "Could not access image."},
            "subObjectives": [],
            "findings": [],
            "contradictions": [],
            "limitations": [f"Image file retrieval failed for: {', '.join(missing_images)} — visual evidence unavailable"],
            "uncertainty": "No image content was analyzed due to storage access failure.",
            "sourcesUsed": [],
            "risk": "unknown",
            "evidenceSignals": [],
        }
    if not any(p.get("file") for p in parts):
        return {
            "conclusion": "insufficient_evidence",
            "confidence": 0,
            "answer": "No image was submitted for analysis.",
            "assessmentReasoning": "The investigation requires an image input, but none was provided.",
            "mediaAuthenticity": {"verdict": "unknown", "reasoning": "No image submitted."},
            "contextualAccuracy": {"verdict": "unknown", "reasoning": "No image submitted."},
            "subObjectives": [],
            "findings": [],
            "contradictions": [],
            "limitations": ["No image input provided"],
            "uncertainty": "Cannot analyze without image content.",
            "sourcesUsed": [],
            "risk": "unknown",
            "evidenceSignals": [],
        }
    result = await _run_analysis(inv, evidence, system_prompt, parts, text_fallback=False)
    # Deterministic cross-check of category counts against the enumerated
    # instances: a reported count is only as reliable as the instance list that
    # backs it. Corrected/unverifiable counts surface as limitations.
    counted, count_notes = _reconcile_object_counts(result)
    if counted is not None:
        result["objectCounts"] = counted
        if count_notes:
            result["limitations"] = (result.get("limitations") or []) + count_notes
    result = img_inv_helpers.finalize_image_investigation(inv, evidence, result)
    # Persist sub-objectives so the evidence graph can use them
    raw_sub = result.pop("subObjectives", None)
    if raw_sub and isinstance(raw_sub, list):
        inv["subObjectives"] = raw_sub
    return result


async def _video_analyzer(inv, evidence):
    system_prompt = (
        "You are Inquvia's video analyst. Your job is to answer the user's question "
        "using ONLY the provided evidence (file-level signals, timestamped frames with "
        "visual observations, audio transcript with segment timestamps, and any acquired "
        "evidence). Do not use internal knowledge to fill gaps.\n\n"
        "FIRST, classify the user's question into its category, then answer using ONLY "
        "the evidence that category depends on (categories generalize; never rely on a "
        "specific wording):\n"
        "- SCENE/EVENT SUMMARY ('what is happening', describe the video): scenes, objects, "
        "actions, people, sequence across frames + transcript.\n"
        "- OBJECT/ENTITY ID ('what car', 'what object', identify a thing): frames showing the "
        "object + visual features; name it only if a frame actually shows it.\n"
        "- SPEECH CONTENT ('what does the person say'): the transcript and its segments only. "
        "Quote verbatim.\n"
        "- VISIBLE TEXT/OCR ('what is written on the board', 'read the text'): frame "
        "observations that mention readable text; transcribe only text that is visible.\n"
        "- COUNTING/TRACKING ('how many people', 'did the person enter'): count/track people "
        "across multiple timestamped frames; give the timestamps used.\n"
        "- TEMPORAL ORDER ('what happened first'): use frame timestamps + transcript segment "
        "order to establish the sequence.\n"
        "- AUDIO/VIDEO SYNC: use transcript segment timing against frame timestamps; flag "
        "only observable mismatches.\n"
        "- MANIPULATION/EDITS ('was anything edited out'): frame continuity + forensic signals.\n"
        "- AI-GENERATED/DEEPFAKE: frames, motion, faces, audio and forensic signals together.\n"
        "- LOCATION ('where/which location'): visible signs, landmarks, architecture, environment.\n"
        "- DATE/TIME ('which date'): on-screen text, screens, embedded timestamps, metadata, clues.\n"
        "- DOCUMENT IN VIDEO: extract the document's content from the relevant frames (OCR).\n"
        "- PRODUCT ('which product'): frames showing the product + visible features.\n"
        "- TWO-VIDEO COMPARISON ('are these the same', 'what changed'): compare frames, audio, "
        "timing and metadata across the submitted videos.\n"
        "- CLAIM VERIFICATION ('is the claim true'): FIRST determine what the video itself "
        "shows/says from the evidence; only then, if external verification is required, note "
        "that it requires outside evidence you do not have.\n\n"
        "Read the user's question carefully and determine what kind of answer is needed:\n"
        "- If the question asks to EXTRACT, TRANSCRIBE, DESCRIBE, SUMMARIZE, or LIST "
        "content: provide a direct answer from the evidence. Use conclusion 'answered' "
        "if fully answered, 'inconclusive' if partial. Return an 'answer' field.\n"
        "- If the question asks whether content is GENUINE, MANIPULATED, FAKE, AI-GENERATED, "
        "or RISKY: issue a forensic verdict ONLY when observable signals support it. "
        "Use conclusion 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'.\n"
        "- If the question asks WHETHER A CLAIM IS SUPPORTED: assess the claim against "
        "the evidence. Use appropriate conclusion.\n"
        "- In ALL cases: distinguish spoken words (from transcript + timestamps) from "
        "visual observations (from frames + timestamps) from inference. Cite timestamps.\n"
        "- If evidence only partially answers the question, explicitly state what IS "
        "answered and what is NOT. Use 'insufficient_evidence' or 'inconclusive' honestly.\n"
        "- State limitations explicitly. Express confidence honestly (0-100).\n\n"
        "Return ONLY JSON with this exact schema:\n"
        "{ conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
        "confidence: number 0-100, "
        "answer: string (your direct answer to the user's question, or explicit statement that evidence cannot answer it), "
        "assessmentReasoning: string (explain how the evidence supports your answer, distinguishing spoken words from visual observations from inference), "
        "questionCategory: string (one of: scene_summary|object_entity|speech_content|visible_text|count_track|temporal_order|audio_video_sync|manipulation|ai_generated|location|date_time|document|product|comparison|claim_verification), "
        "findings: string[], contradictions: string[], limitations: string[], "
        "uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', "
        "evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }"
    )
    videos = [i for i in (inv.get("inputs") or []) if i.get("type") == "video"]
    from ..libraries.planner import video_question_needs_frames
    question = (inv.get("question") or "").strip()
    needs_frames = video_question_needs_frames(question)
    parts = []
    for input_ in videos:
        label = input_.get("content") or input_.get("fileName") or "video"
        parts.append({"text": f"VIDEO_CONTEXT: {label}"})
        extract = prepare_video(input_)  # cached from the evidence checks
        processor = VideoProcessor()
        if extract.get("inspection"):
            parts.append({"text": processor.describe(extract["inspection"], label)})
        elif extract.get("fallbackSignals"):
            parts.append({"text": extract["fallbackSignals"]})
        frames = extract.get("frames") or []
        if frames:
            from ..libraries import evidence_checks as checks_lib
            observations = checks_lib.frame_observations_by_time(extract)
            if extract.get("frameObservations") is None and extract.get("state") == "ok":
                await checks_lib._observe_frames(input_, label, extract)
                observations = checks_lib.frame_observations_by_time(extract)
            if needs_frames:
                for frame in frames:
                    raw = frame_payload_bytes(frame)
                    if raw:
                        parts.append({
                            "file": {
                                "mimeType": "image/jpeg",
                                "base64": base64.b64encode(raw).decode("ascii"),
                            }
                        })
                        parts.append({"text": f"FRAME at t={frame['timestamp']:.2f}s"})
            # Observation text is cheap and always useful, even for
            # speech-only questions; only the binary frames are omitted.
            for frame in frames:
                obs = observations.get(round(frame["timestamp"], 2))
                if obs and obs.get("visibleContent"):
                    parts.append({
                        "text": f"Directly visible at t={frame['timestamp']:.2f}s: {obs['visibleContent']}"
                    })
        transcript = extract.get("transcript")
        if transcript:
            window = extract.get("transcriptWindowSeconds")
            label_w = ""
            if window:
                label_w = f" (transcribed window: first {window:.0f}s)"
            parts.append({"text": f"AUDIO_TRANSCRIPT{label_w}:\n{transcript[:6000]}"})
            if extract.get("transcriptSegments"):
                seg_text = "\n".join(
                    f"[{s['start']:.2f}s-{s['end']:.2f}s] {s['text']}"
                    for s in extract["transcriptSegments"]
                )
                parts.append({"text": f"AUDIO_TRANSCRIPT_SEGMENTS:\n{seg_text[:4000]}"})
        limitations = extract.get("limitations") or []
        if not frames and not limitations:
            limitations.append("Frame extraction produced no frames; visual evidence is unavailable.")
        if not (extract.get("inspection") or {}).get("hasAudio") and extract.get("state") == "ok":
            limitations.append("No audio track was detected; audio analysis is not applicable.")
        elif extract.get("audio") and not transcript:
            limitations.append("Audio stream present but no transcript available; audio evidence is unavailable.")
        if limitations:
            parts.append({"text": "VIDEO_PROCESSING_LIMITATIONS: " + "; ".join(limitations)})
    if not any(p.get("file") for p in parts):
        context = _first_text_input(inv) or ""
        if context:
            parts.append({"text": f"VIDEO_CONTEXT: {context}"})
    if len(videos) > 1:
        parts.append({"text": f"NOTE: {len(videos)} videos were submitted -- compare them against each other."})
    parts.append({"text": f"USER_QUESTION: {question}"})
    return await _run_analysis(inv, evidence, system_prompt, parts, text_fallback=False)


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
    "from the rendered image -- never invent a source). "
    "Classify the nature of each passage: 'stated_fact' (the document directly asserts a fact), "
    "'document_claim' (the document itself makes/asserts a claim, distinct from established fact), "
    "'observation' (something the document records or reports), 'interpretation' (your inference drawn from "
    "the text), 'uncertain' (the text is ambiguous), or 'missing' (the document lacks this; see missingInformation). "
    "Mark each passage's relationship to the question as 'supporting', 'contradictory', or 'unestablished'. "
    "If neither supporting nor contradictory evidence is established, represent that accurately; do not force "
    "a verdict. "
    "For authenticity/verification questions: distinguish evidence contained in the document itself from "
    "independent authentication -- never claim authenticity merely because the document looks official. "
    "If the question can only be answered with information the document cannot provide, identify in "
    "additionalSourcesNeeded what other evidence/source would be required, and do not silently use another source. "
)

_DOCUMENT_JSON_SCHEMA = (
    "{ conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
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
        "text": f"INVESTIGATION_OBJECTIVE (the user's question -- your sole objective): {inv.get('question')}\n\n"
                f"ACQUIRED EVIDENCE:\n{evidence_text}"
    })
    raw_text = await ai_lib.call_ai_with_parts(system_prompt, context_parts)
    raw = ai_lib.parse_ai_json(raw_text) or {}
    result = _merge_ai_raw(inv, evidence, raw)
    # The document's relationship summary comes from the SELECTED passages, not
    # from counting every page record. Zero on both sides = no relationship was
    # established, represented accurately (never forced).
    items = [i for i in (raw.get("evidenceItems") or []) if isinstance(i, dict)]
    
    # Correctly group status codes: successful = 2xx, unsuccessful = 4xx/5xx. 3xx must be excluded.
    def is_successful(item):
        status = item.get("status")
        if status is not None and isinstance(status, int):
            return 200 <= status < 300
        return item.get("relationship") == "supporting"

    def is_unsuccessful(item):
        status = item.get("status")
        if status is not None and isinstance(status, int):
            return 400 <= status < 600
        return item.get("relationship") == "contradictory"

    supporting = [i for i in items if is_successful(i)]
    contradicting = [i for i in items if is_unsuccessful(i)]
    
    if items:
        result["evidenceRelationships"] = {
            "supporting": len(supporting),
            "contradicting": len(contradicting),
            "established": bool(supporting or contradicting),
        }
    return result


async def _compute_document_analysis(inv, evidence, input_) -> dict | None:
    """Deterministic full-file computation for structured sources.

    When the user's question needs aggregate statistics over the WHOLE file
    (counts, averages, sums, groupings, ranks, comparisons...), the uploaded
    source is parsed and aggregated deterministically (streaming, never fed to
    the model in full). The model receives schema + computed results + trace +
    samples and explains them. Returns None when the document is prose (the
    caller falls back to page-extraction analysis).
    """
    question = (inv.get("question") or "").strip()
    if not compute_structured.requires_full_compute(question):
        return None
    if not input_ or not input_.get("filePath"):
        return None
    extraction = input_.get("documentExtraction") or {}
    if extraction.get("extractionSource") not in ("plain_text", "text_layer"):
        return None
    data = signals_lib.load_bytes(input_["filePath"])
    if not data:
        return None
    filename = input_.get("fileName") or input_.get("content") or "uploaded file"
    mime = input_.get("mimeType")
    profile = compute_structured._scan(data, mime, filename)
    if not profile:
        return None
    profile["source"] = filename

    try:
        sys_prompt, parts = compute_structured.build_plan_prompt(question, profile)
        raw_plan = await ai_lib.call_ai_with_parts(sys_prompt, parts)
        plan = compute_structured.parse_plan(raw_plan)
    except Exception:
        plan = []

    computation = compute_structured.execute(data, profile, plan)

    now = datetime.now(timezone.utc).isoformat()
    for rec in compute_structured.computation_evidence_records(computation, filename):
        ev = {
            "id": f"ev_calc_{secrets.token_urlsafe(6)[:8]}",
            "type": "document",
            "source": f"Inquvia computation: {filename}",
            "finding": rec["finding"],
            "signal": rec["signal"],
            "status": "collected",
            "confidence": None,
            "timestamp": now,
            "metadata": {"origin": "computation", "checkCapability": "document_compute",
                         **rec["metadata"]},
        }
        evidence.append(ev)
        inv.setdefault("evidence", []).append(ev)

    inv["computation"] = computation

    system, parts = compute_structured.build_reasoning_prompt(question, profile, computation)
    raw = ai_lib.parse_ai_json(await ai_lib.call_ai_with_parts(system, parts)) or {}
    if raw:
        result = _merge_ai_raw(inv, evidence, raw)
    else:
        # Deterministic fallback answer when the reasoning model returns nothing.
        result = heuristic_analysis(inv, evidence)
        result["conclusion"] = "answered" if computation["complete"] else "inconclusive"
        result["confidence"] = 80 if computation["complete"] else 40
        summary = "; ".join(
            f"{m['name']} = {m['result']}" for m in computation["metrics"]
            if not isinstance(m["result"], list)
        )
        prefix = (f"A complete analysis of all {computation['recordsProcessed']} records in "
                  f"{filename}." if computation["complete"]
                  else f"An analysis of only {computation['recordsProcessed']} of "
                       f"{computation['recordsAvailable']} records in {filename}.")
        result["answer"] = f"{prefix} {summary}"
        result["conclusionText"] = "Answer: " + result["answer"]
        result["assessmentReasoning"] = (
            f"Deterministic computation over the uploaded document "
            f"({computation['recordsProcessed']} records, {computation['unparsedLines']} unparsed)."
        )
    result["computation"] = computation
    result["sourcesUsed"] = result.get("sourcesUsed") or [filename]
    if not computation["complete"]:
        result["limitations"] = (result.get("limitations") or []) + [
            f"Only {computation['recordsProcessed']} of {computation['recordsAvailable']} records "
            f"could be processed ({computation['unparsedLines']} lines unparsed); the analysis is "
            "partial, not a whole-file claim."
        ]
    if computation.get("skippedMetrics"):
        reasons = sorted({m["name"] for m in computation["skippedMetrics"]})
        result["limitations"] = (result.get("limitations") or []) + [
            f"Requested metric(s) could not be computed (field not present in the source): "
            f"{', '.join(reasons)}"
        ]
    return result


async def _document_analyzer(inv, evidence):
    input_ = _find_input(inv, "document")
    pages = await _load_document_pages(inv, input_)
    if not pages:
        # No readable document content → honest insufficiency, never fabricated.
        return heuristic_analysis(inv, evidence)

    # Structured/deterministic path: when the question needs whole-file
    # statistics over a record-structured source, compute over every record
    # instead of sending only a truncatable excerpt to the model.
    computed = await _compute_document_analysis(inv, evidence, input_)
    if computed is not None:
        return computed

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
        "You are Inquvia's web source analyst. "
        "Your PRIMARY objective is to answer the user's exact question using the extracted page content. "
        "Follow this process strictly:\n"
        "1. Read the user's question and identify every sub-objective.\n"
        "2. Search the FULL_PAGE_TEXT for passages that directly address each sub-objective.\n"
        "3. Quote or paraphrase the exact relevant passage(s) before forming your answer.\n"
        "4. Prefer exact values from the source over approximate summaries. "
        "If the source states a specific number, date, or duration, use that exact value — "
        "do NOT substitute a rounded, approximate, or generic value.\n"
        "5. If the source contains conflicting values, report the conflict explicitly in 'contradictions'.\n"
        "6. Cross-check your final answer against the quoted passages before returning it. "
        "If your answer states a fact not present in the passages, remove or qualify it.\n"
        "7. For every major factual statement in the answer, assign 'supporting' to the "
        "evidence item(s) that contain the supporting passage in evidenceSignals. "
        "A successful page retrieval that contains the answer MUST be marked 'supporting', "
        "not 'uncertain'. Only mark an evidence item 'uncertain' if it genuinely neither "
        "supports nor contradicts the answer.\n"
        "8. Use conclusion 'answered' when the page content directly answers the question. "
        "Use 'inconclusive' only when the content is ambiguous or conflicting. "
        "Use 'insufficient_evidence' only when the required information is genuinely absent from the page.\n"
        "9. Confidence must reflect evidence quality: high (80-95) when exact values are "
        "present and unambiguous in the source; moderate (50-75) when inferred or partially "
        "supported; low (<50) when conflicting or absent. Do NOT return high confidence when "
        "your answer contains a value that differs from what the source states.\n"
        "10. Credibility signals (DNS, SSL, HTTP status) are secondary context — do not let "
        "them override a factual answer that is directly supported by the page content. "
        "A successful HTTP retrieval does NOT make the answer uncertain; it is evidence that "
        "the page was accessible and its content is available for analysis.\n"
        "11. The user's exact question (from QUESTION field) is the investigation objective — "
        "preserve it verbatim in your reasoning.\n"
        "Return ONLY JSON: { conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
        "confidence: number 0-100, answer: string, assessmentReasoning: string, "
        "findings: string[], contradictions: string[], limitations: string[], uncertainty: string, "
        "sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', "
        "evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }."
    )
    url_input = _find_input(inv, "url")
    inspection = inv.get("webInspection")

    # Build context: URL + retrieval status + full extracted page text.
    # The full text is the primary evidence body; the AI must ground its
    # answer in it rather than relying on internal knowledge.
    url_str = url_input.get("content") if url_input else _first_text_input(inv) or inv.get("question")
    context_parts = []

    # Retrieval status block (separate from answer uncertainty).
    if inspection:
        status = inspection.get("statusCode")
        is_online = inspection.get("isOnline")
        ssl_valid = inspection.get("sslValid")
        title = inspection.get("title") or ""
        access = inspection.get("access") or {}
        retrieval_lines = [
            f"URL: {url_str}",
            f"HTTP_STATUS: {status or 'unknown'}",
            f"ONLINE: {is_online}",
            f"SSL_VALID: {ssl_valid}",
        ]
        if title:
            retrieval_lines.append(f"PAGE_TITLE: {title}")
        if access.get("blocked"):
            retrieval_lines.append(f"ACCESS_BLOCKED: {access.get('reason', 'unknown reason')}")
        if inspection.get("renderNote"):
            retrieval_lines.append(f"RENDER_NOTE: {inspection['renderNote']}")
        context_parts.append({"text": "RETRIEVAL_STATUS:\n" + "\n".join(retrieval_lines)})

        # Full page text — the primary evidence body for answering the question.
        # Prefer fullText (complete bounded extraction); fall back to content chunk.
        full_text = inspection.get("fullText") or inspection.get("content") or ""

        # Also pull full text from evidence metadata if the inspection on inv
        # was stored before the fullText field was added.
        if not full_text:
            for ev in evidence:
                meta = ev.get("metadata") or {}
                if meta.get("checkCapability") == "content_extract" and meta.get("fullText"):
                    full_text = meta["fullText"]
                    break

        if full_text:
            context_parts.append({"text": f"FULL_PAGE_TEXT (use this to answer the question):\n{full_text[:50000]}"})
            # Structured headings as a navigation aid.
            headings = inspection.get("headings") or []
            if headings:
                heading_lines = [f"{'#' * h['level']} {h['text']}" for h in headings[:40]]
                context_parts.append({"text": "PAGE_HEADINGS:\n" + "\n".join(heading_lines)})
        else:
            context_parts.append({"text": f"URL: {url_str}\n\nNo page content could be extracted (access blocked or network failure)."})
    else:
        context_parts.append({"text": f"URL: {url_str}\n\nNo live web inspection was performed."})

    return await _run_analysis(inv, evidence, system_prompt, context_parts)


async def _data_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's structured-data analyst. Inspect the submitted CSV/JSON dataset for anomalies, inconsistencies, missing values, or suspicious patterns, "
        "together with acquired evidence. Express confidence honestly. "
        "If the question asks to extract, summarize, or list data: provide the extracted content in 'answer' "
        "and use conclusion 'answered'. If the question asks whether the data is anomalous/consistent/suspicious: "
        "issue an assessment ONLY when observable signals support it. "
        "Return ONLY JSON: { conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', "
        "confidence: number 0-100, answer: string, assessmentReasoning: string, "
        "findings: string[], contradictions: string[], limitations: string[], uncertainty: string, "
        "sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', "
        "evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }."
    )
    input_ = _find_input(inv, "data") or _find_input(inv, "text")
    content = None
    if input_ and input_.get("filePath"):
        content = read_stored_text(input_["filePath"], 30000)
    data_context = content or (input_.get("content") if input_ else None) or inv.get("question")
    return await _run_analysis(inv, evidence, system_prompt, [{"text": f"DATA_CONTEXT:\n{data_context}"}])


async def _audio_analyzer(inv, evidence):
    system_prompt = _QUESTION_RULE + (
        "You are Inquvia's audio analyst. Assess the submitted audio recording(s) using the extracted FILE_LEVEL_SIGNALS (container, sample rate, channels, bit depth, duration), the audio transcript with segment timestamps, and any acquired evidence. Do not use internal knowledge to fill gaps. If the question asks to transcribe, extract, describe, or summarize the audio: provide the transcript/content in 'answer' and use conclusion 'answered' if fully answered, 'inconclusive' if partial. If the question asks whether the audio is genuine/manipulated/AI-generated/risky: issue a forensic verdict ONLY when observable signals support it. In ALL cases: distinguish spoken words (from transcript + timestamps) from inference. Cite timestamps. If evidence only partially answers the question, explicitly state what IS answered and what is NOT. Use 'insufficient_evidence' or 'inconclusive' honestly. State limitations explicitly. Express confidence honestly (0-100). "
        "When multiple recordings are provided, compare them against each other. "
        "Express confidence honestly; explicit uncertainty is expected. "
        "Return ONLY JSON: { conclusion: 'answered'|'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, answer: string, assessmentReasoning: string, transcript: string, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown', evidenceSignals: [{'id': string, 'signal': 'supporting'|'contradictory'|'uncertain'}] }."
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
        # Include transcript evidence from evidence checks (cached on mediaExtraction)
    from ..libraries import evidence_checks as checks_lib
    for input_ in audios:
        extract = input_.get("mediaExtraction") or {}
        transcript = extract.get("transcript")
        if transcript:
            window = extract.get("transcriptWindowSeconds")
            label_w = f" (transcribed window: first {window:.0f}s)" if window else ""
            parts.append({"text": f"AUDIO_TRANSCRIPT{label_w}:\n{transcript[:6000]}"})
            segments = extract.get("transcriptSegments")
            if segments:
                seg_text = "\n".join(f"[{s['start']:.2f}s?{s['end']:.2f}s] {s['text']}" for s in segments)
                parts.append({"text": f"AUDIO_TRANSCRIPT_SEGMENTS:\n{seg_text[:4000]}"})
    if not any(p.get("file") for p in parts):
        context = _first_text_input(inv) or ""
        if context:
            parts.append({"text": f"AUDIO_CONTEXT: {context}"})
    if len(audios) > 1:
        parts.append({"text": f"NOTE: {len(audios)} audio recordings were submitted -- compare them against each other."})
    parts.append({"text": f"USER_QUESTION: {inv.get('question')}"})
    return await _run_analysis(inv, evidence, system_prompt, parts, text_fallback=False)


def json_dumps(obj):
    import json
    try:
        return json.dumps(obj, indent=2)
    except Exception:
        return str(obj)


register_analyzer("claim-investigation", _claim_analyzer)
register_analyzer("image-investigation", _image_analyzer)
register_analyzer("image-batch-investigation", _image_analyzer)
register_analyzer("video-investigation", _video_analyzer)
register_analyzer("document-investigation", _document_analyzer)
register_analyzer("source-investigation", _source_analyzer)
register_analyzer("data-investigation", _data_analyzer)
register_analyzer("audio-investigation", _audio_analyzer)
