"""Evidence requirement planning."""

import json
import re
from typing import List, Optional
from ..libraries import ai as ai_lib

# Executable evidence checks — each capability here should map to a runner in
# evidence_checks.py. Catalog entries without a runner are planner-only stubs
# (the AI may select them for claim investigations, but image checks skip unknown
# capabilities at execution time).
EXECUTABLE_CHECKS = [
    # --- Image: implemented (evidence_checks.py) ---
    {"capability": "image_metadata", "type": "image", "name": "Image metadata / EXIF inspection",
     "desc": "Extracts image format, dimensions, mode and EXIF/editor-software tags."},
    {"capability": "image_visual_observation", "type": "image", "name": "Visual scene observation",
     "desc": "Multimodal reading of what is directly visible in the image (question-independent)."},
    {"capability": "image_provenance", "type": "image", "name": "Image provenance & metadata analysis",
     "desc": "Extracts image format, dimensions, mode and any EXIF/editor-software tags."},
    {"capability": "image_manipulation", "type": "image", "name": "Image manipulation & integrity analysis",
     "desc": "Error Level Analysis, compression/quality and metadata-tamper forensics."},
    {"capability": "image_reverse_search", "type": "image", "name": "Reverse-image & provenance search",
     "desc": "Near-duplicates across the web and earliest-source dating (SerpAPI when configured)."},
    {"capability": "image_authoritative_search", "type": "image", "name": "Authoritative web source search",
     "desc": "Web search for historical events, archives, and claim corroboration."},
    {"capability": "image_ocr", "type": "image", "name": "OCR / visible text extraction",
     "desc": "Extracts visible text for verification against external sources."},
    {"capability": "image_medical", "type": "image", "name": "Medical image forensic analysis",
     "desc": "Medical image type identification, file-level facts (requires opt-in)."},
    {"capability": "image_compare", "type": "image", "name": "Two-image comparison",
     "desc": "Compares two submitted images for similarity, cropping, and probable edits."},
    {"capability": "image_c2pa", "type": "image", "name": "C2PA / Content Credentials",
     "desc": "Detects C2PA manifests and Content Credentials markers in the file."},
    {"capability": "ai_detection", "type": "image", "name": "AI-generation detection",
     "desc": "Visual AI artifacts and generative indicators (forensics + multimodal reasoning)."},
    {"capability": "image_quality", "type": "image", "name": "Image quality & recompression forensic",
     "desc": "Blur, resolution, compression artifacts (partially via manipulation forensics)."},
    {"capability": "pii_detection", "type": "image", "name": "Privacy & PII detection",
     "desc": "Faces, addresses, IDs, license plates, QR codes, barcodes."},
    {"capability": "safety_analysis", "type": "image", "name": "Safety & hazard detection",
     "desc": "Dangerous situations, weapons, accidents, hazardous conditions."},
    {"capability": "document_analysis", "type": "image", "name": "Document forensic analysis",
     "desc": "Receipts, invoices, certificates, IDs, signatures (OCR + visual analysis)."},
    {"capability": "commercial_verification", "type": "image", "name": "Commercial & product authenticity",
     "desc": "Product authenticity, packaging, labels, advertisements."},
    {"capability": "scientific_technical", "type": "image", "name": "Scientific & technical analysis",
     "desc": "Charts, diagrams, lab images, engineering photos."},
    {"capability": "geospatial_analysis", "type": "image", "name": "Geospatial & satellite analysis",
     "desc": "Satellite/aerial imagery, land-use, construction, environmental change."},
    {"capability": "before_after_analysis", "type": "image", "name": "Before/after comparative analysis",
     "desc": "Construction, damage, restoration, product changes (needs two images)."},
    {"capability": "logo_watermark", "type": "image", "name": "Logo & watermark verification",
     "desc": "Logos, watermarks, official seals."},
    {"capability": "meme_context", "type": "image", "name": "Meme & media context tracing",
     "desc": "Caption/context changes over time (needs reverse search + timeline)."},
    {"capability": "copyright_attribution", "type": "image", "name": "Ownership & copyright attribution",
     "desc": "Source attribution, licensing clues, watermark tracing."},
    {"capability": "accessibility_description", "type": "image", "name": "Accessibility & scene summary",
     "desc": "Alt text and scene descriptions."},
    {"capability": "batch_investigation", "type": "image", "name": "Batch image investigation",
     "desc": "Duplicate clusters and common sources across many images."},
    {"capability": "screenshot_analysis", "type": "image", "name": "Screenshot verification",
     "desc": "UI consistency, typography, interface version checks."},
    {"capability": "geolocation", "type": "image", "name": "Geolocation & geographic consistency",
     "desc": "Signage, language, landmarks to verify location claims."},
    {"capability": "event_identification", "type": "image", "name": "Event identification",
     "desc": "Historical, news, or public event verification."},

    # --- Non-image ---
    # --- Video Authenticity ---
    {"capability": "video_analysis", "type": "video", "name": "Video container & encoding analysis", "desc": "Inspect container/stream metadata (codec, dimensions, fps, audio)."},
    {"capability": "frame_evidence", "type": "video", "name": "Timestamped frame evidence", "desc": "Extract timestamped key frames with direct visual observations."},
    {"capability": "audio_transcription", "type": "video", "name": "Audio transcription", "desc": "Transcribe the audible speech track with segment timestamps."},
    {"capability": "video_authenticity", "type": "video", "name": "Video authenticity", "desc": "Determine if video is genuine, AI-generated, or manipulated."},
    {"capability": "video_ai_detection", "type": "video", "name": "AI-generated video detection", "desc": "Detect deepfakes and generative AI artifacts."},
    {"capability": "video_manipulation", "type": "video", "name": "Video manipulation/forensics", "desc": "Detect editing, compositing, and splicing artifacts."},
    {"capability": "video_source", "type": "video", "name": "Video source/origin", "desc": "Identify original publication and source."},
    {"capability": "video_reverse_matching", "type": "video", "name": "Reverse-video matching", "desc": "Match video clips against known databases."},
    {"capability": "video_event_verification", "type": "video", "name": "Event verification", "desc": "Verify event correspondence."},
    {"capability": "video_date_time", "type": "video", "name": "Date/time verification", "desc": "Check temporal consistency."},
    {"capability": "video_location", "type": "video", "name": "Location verification", "desc": "Verify geographic location."},
    {"capability": "video_timeline", "type": "video", "name": "Timeline reconstruction", "desc": "Reconstruct event sequence."},
    {"capability": "video_context", "type": "video", "name": "Context verification", "desc": "Verify contextual accuracy."},
    {"capability": "video_caption_verification", "type": "video", "name": "Caption/title verification", "desc": "Verify caption accuracy."},
    {"capability": "video_claim_verification", "type": "video", "name": "Claim verification", "desc": "Evaluate evidence against claim."},
    {"capability": "video_contradiction", "type": "video", "name": "Contradiction detection", "desc": "Search for evidence contradictions."},
    {"capability": "video_evidence_gaps", "type": "video", "name": "Evidence gaps", "desc": "Identify missing evidence."},
    {"capability": "video_provenance", "type": "video", "name": "Video provenance", "desc": "Track provenance chain."},
    {"capability": "video_metadata", "type": "video", "name": "Video metadata", "desc": "Analyze container/stream metadata."},

    # --- Visual Investigation ---
    {"capability": "vid_object_id", "type": "video", "name": "Object identification", "desc": "Identify objects in video."},
    {"capability": "vid_person_id", "type": "video", "name": "Person/identity investigation", "desc": "Identify people."},
    {"capability": "vid_face_manipulation", "type": "video", "name": "Face manipulation", "desc": "Detect face replacement/edits."},
    {"capability": "vid_scene_understanding", "type": "video", "name": "Scene understanding", "desc": "Contextual scene analysis."},
    {"capability": "vid_text_ocr", "type": "video", "name": "Text/OCR from frames", "desc": "OCR from video frames."},
    {"capability": "vid_document_analysis", "type": "video", "name": "Document-in-video analysis", "desc": "Analyze documents in frames."},
    {"capability": "vid_logo_watermark", "type": "video", "name": "Logo/watermark verification", "desc": "Identify logos/seals."},
    {"capability": "vid_commercial_verification", "type": "video", "name": "Product/commercial verification", "desc": "Product authenticity."},
    {"capability": "vid_historical_verification", "type": "video", "name": "Historical footage verification", "desc": "Verify historical footage."},
    {"capability": "vid_scientific_analysis", "type": "video", "name": "Scientific/technical footage analysis", "desc": "Technical analysis."},
    {"capability": "vid_geospatial_analysis", "type": "video", "name": "Geospatial analysis", "desc": "Geospatial feature analysis."},
    {"capability": "vid_before_after", "type": "video", "name": "Before/after comparison", "desc": "Comparative analysis."},
    {"capability": "vid_two_video_comparison", "type": "video", "name": "Two-video comparison", "desc": "Compare two videos."},

    # --- Audio Investigation ---
    {"capability": "aud_authenticity", "type": "audio", "name": "Audio authenticity", "desc": "Check audio integrity."},
    {"capability": "aud_voice_deepfake", "type": "audio", "name": "Voice/deepfake detection", "desc": "Detect synthetic voices."},
    {"capability": "aud_transcription", "type": "audio", "name": "Speech transcription", "desc": "Transcribe speech."},
    {"capability": "aud_speaker_consistency", "type": "audio", "name": "Speaker/voice consistency", "desc": "Verify voice consistency."},
    {"capability": "aud_av_sync", "type": "audio", "name": "Audio-video synchronization", "desc": "Check AV sync."},
    {"capability": "aud_manipulation", "type": "audio", "name": "Audio manipulation/splicing", "desc": "Detect audio edits."},
    {"capability": "aud_translation", "type": "audio", "name": "Translation/subtitle verification", "desc": "Check translations."},

    # --- Safety/Privacy/Quality ---
    {"capability": "vid_privacy_pii", "type": "video", "name": "Privacy/PII detection", "desc": "Detect PII in video."},
    {"capability": "vid_safety_hazard", "type": "video", "name": "Safety/hazard detection", "desc": "Detect safety hazards."},
    {"capability": "vid_quality_analysis", "type": "video", "name": "Video quality/compression analysis", "desc": "Analyze quality/artifacts."},

    {"capability": "document_verify", "type": "document", "name": "Document text extraction",
     "desc": "Extracts the document text layer for the answer and for inconsistency checking."},
    {"capability": "data_consistency", "type": "data", "name": "Structured data consistency check",
     "desc": "Profiles CSV rows/columns or JSON records/keys and flags empty cells."},
    {"capability": "content_extract", "type": "url", "name": "URL content inspection",
     "desc": "Live DNS, TLS certificate and page-title/snippet inspection of a URL."},
]

EXECUTABLE_BY_CAP = {c["capability"]: c for c in EXECUTABLE_CHECKS}

IMAGE_BASELINE_CHECKS = ["image_metadata", "image_visual_observation", "image_manipulation"]
# The layered image pipeline is a fixed, deterministic order, not an open-ended
# AI selection:
#   Layer 1  metadata / provenance observations  (image_metadata)
#   Layer 2  reverse-image / near-duplicate search
#   Layer 3  earliest-source dating (same check as layer 2)
#   Layer 4  context verification (authoritative / historical web search)
#   Layer 5  manipulation forensics
# Every layer either runs or reports an honest unavailability — never silently
# skipped. `plan_image_investigation` always plans these and may add more
# question-matched checks on top.
IMAGE_LAYER_CHECKS = [
    "image_metadata",
    "image_reverse_search",
    "image_authoritative_search",
    "image_manipulation",
]

_IMAGE_INTENT_PATTERNS: dict[str, list[str]] = {
    "ai_detection": [
        r"\b(ai.?generated|ai.?made|midjourney|dall-?e|stable diffusion|deepfake|synthetic)\b",
        r"\b(generated image|not real|computer.?generated)\b",
    ],
    "image_c2pa": [
        r"\b(c2pa|content credentials|contentcredentials|provenance chain|credentials)\b",
    ],
    "image_reverse_search": [
        r"\b(reverse|duplicate|same image|viral|repost|earliest|original source|provenance|found online)\b",
        r"\b(circulating|published elsewhere|where.*from|miscaption|misinformation|old image|meme|copyright)\b",
    ],
    "image_authoritative_search": [
        r"\b(apollo|nasa|historical|archive|mission|disaster|flood|protest|ceremony|event)\b",
        r"\b(when|where|date|year|location|geolocation|taken in|yesterday|recent|timeline)\b",
        r"\b(verify|actually|prove|claim|caption|context|hyderabad|from \d{4})\b",
        r"\b(is this from|does this show|really show|taken at|happened)\b",
    ],
    "image_ocr": [
        r"\b(text|ocr|screenshot|certificate|announcement|headline|whatsapp|twitter|instagram)\b",
        r"\b(facebook|bank|payment|ui|read|written|say|label|sign|receipt|invoice|barcode|qr)\b",
    ],
    "pii_detection": [
        r"\b(face|privacy|pii|personal information|license plate|address|identify|qr code|barcode)\b",
    ],
    "safety_analysis": [
        r"\b(weapon|gun|accident|danger|hazard|explosion|fire|violence|unsafe)\b",
    ],
    "document_analysis": [
        r"\b(receipt|invoice|certificate|passport|id card|signature|document|license)\b",
    ],
    "commercial_verification": [
        r"\b(counterfeit|authentic product|packaging|label|brand|logo|advertisement|fake product)\b",
    ],
    "scientific_technical": [
        r"\b(chart|diagram|graph|lab|microscop|engineering|technical|plot|axis)\b",
    ],
    "geospatial_analysis": [
        r"\b(satellite|aerial|land.?use|construction progress|environmental|earth observation)\b",
    ],
    "meme_context": [
        r"\b(meme|viral|miscaption|caption change|context change|repurposed)\b",
    ],
    "copyright_attribution": [
        r"\b(copyright|ownership|attribution|licensed|getty|reuters|who owns|photographer)\b",
    ],
    "logo_watermark": [
        r"\b(watermark|logo|seal|official mark|trademark)\b",
    ],
    "accessibility_description": [
        r"\b(alt text|accessibility|describe this image|scene description|what does this show)\b",
    ],
    "image_quality": [
        r"\b(blur|blurry|resolution|quality|compressed|recompression|pixelated)\b",
    ],
    "image_compare": [
        r"\b(compare|same image|which is original|difference|different|both images|two images)\b",
        r"\b(edited from|cropped|modified version|which one)\b",
    ],
    "before_after_analysis": [
        r"\b(before.?after|after.?before|restoration|damage|construction change)\b",
    ],
    "screenshot_analysis": [
        r"\b(screenshot|whatsapp|instagram|twitter|facebook|website|ui|typography|interface|version)\b",
    ],
    "geolocation": [
        r"\b(location|where|city|country|region|landmark|street|landscape|signage|terrain|coordinates)\b",
    ],
    "event_identification": [
        r"\b(event|historical|news|sporting|ceremony|protest|disaster|scientific|political|gathering|launch)\b",
    ],
}

_IMAGE_CHECK_ORDER = [
    "image_metadata",
    "image_visual_observation",
    "image_c2pa",
    "image_manipulation",
    "image_quality",
    "ai_detection",
    "image_ocr",
    "pii_detection",
    "document_analysis",
    "image_reverse_search",
    "image_authoritative_search",
    "meme_context",
    "copyright_attribution",
    "geospatial_analysis",
    "commercial_verification",
    "scientific_technical",
    "logo_watermark",
    "screenshot_analysis",
    "geolocation",
    "event_identification",
    "safety_analysis",
    "accessibility_description",
    "image_compare",
    "before_after_analysis",
    "batch_investigation",
]


class EvidencePlanner:
    """AI-driven evidence planner with deterministic fallback."""

    def __init__(self, executable_checks: List[dict] = EXECUTABLE_CHECKS):
        self.checks = executable_checks
        self.by_cap = {c["capability"]: c for c in executable_checks}

    async def plan(self, question: str, inputs: List[str]) -> List[dict]:
        try:
            return await self._plan_ai(question, inputs)
        except Exception as e:
            print(f"AI planning failed, falling back: {e}")
            return self._plan_fallback(question, inputs)

    async def _plan_ai(self, question: str, inputs: List[str]) -> List[dict]:
        applicable = [c for c in self.checks if not inputs or c["type"] in inputs or c["type"] == "text"]
        catalog = "\n".join(
            f"{c['capability']}: {c['name']} — {c['desc']}"
            for c in applicable
        )
        system_prompt = (
            "You are Inquvia's investigation planner. Identify investigation objectives "
            "from the user question and select relevant evidence capability checks.\n"
            "Return ONLY a JSON object: {\"subObjectives\": [string], \"checks\": [capability_id]}\n"
            f"CATALOG:\n{catalog}"
        )
        user_text = f"QUESTION: {question}\nINPUT_TYPES: {', '.join(inputs)}"
        raw = await ai_lib.call_ai_with_parts(system_prompt, [{"text": user_text}])
        data = json.loads(raw)
        checks = []
        for cap_id in data.get("checks", []):
            if cap_id in self.by_cap:
                checks.append({
                    "id": f"req_{len(checks) + 1}",
                    "type": self.by_cap[cap_id]["type"],
                    "capability": cap_id,
                    "reason": self.by_cap[cap_id]["name"],
                })
        return checks

    def _plan_fallback(self, question: str, inputs: List[str]) -> List[dict]:
        checks = []
        for c in self.checks:
            if not inputs or c["type"] in inputs or c["type"] == "text":
                checks.append({
                    "id": f"req_{len(checks) + 1}",
                    "type": c["type"],
                    "capability": c["capability"],
                    "reason": c["name"],
                })
        return checks[:4]


def _intent_matches(question: str, patterns: list[str]) -> bool:
    return any(re.search(p, question or "", re.I) for p in patterns)


# Capabilities whose evidence depends on the actual frame images (objects,
# people, scene, text, location). A question that matches ONLY non-visual
# categories (pure speech) can be answered from the transcript alone.
# NOTE: vid_person_id is excluded — its pattern ("the person") overlaps
# with speech questions ("what does the person say") and would incorrectly
# force frame images for transcript-only questions.
_VIDEO_VISUAL_CAPS = {
    "vid_scene_understanding", "vid_object_id",
    "vid_text_ocr", "vid_document_analysis", "vid_commercial_verification",
    "video_location", "video_date_time", "video_timeline",
    "video_manipulation", "video_ai_detection", "vid_face_manipulation",
    "aud_av_sync", "vid_two_video_comparison",
}


def video_question_needs_frames(question: str) -> bool:
    """True when answering needs the frame images rather than just the
    transcript. Conservative: any visual-category match (or no match at all)
    keeps frames; only a clearly speech-only question drops them."""
    if not (question or "").strip():
        return True
    matched = [cap for cap, pats in _VIDEO_INTENT_PATTERNS.items() if _intent_matches(question, pats)]
    if not matched:
        return True  # unknown intent → keep frames
    has_audio = "aud_transcription" in matched
    has_visual = any(cap in _VIDEO_VISUAL_CAPS for cap in matched)
    if has_audio and not has_visual:
        return False  # speech-only question → skip frame images, use transcript
    return True


# Question-driven video planning. The video pipeline always extracts the same
# core evidence (inspection + frames + transcript), so intent matching does NOT
# change what is extracted — it tells the planner which of the semantic video
# capabilities the question calls for, so the plan (and the analyzer reading
# it) reflects the category the user is actually asking about. Generic category
# patterns only; no example questions are hardcoded, and the AI planner remains
# the primary classifier for claim/source verticals.
_VIDEO_BASELINE_CHECKS = ["video_analysis", "frame_evidence", "audio_transcription"]

_VIDEO_INTENT_PATTERNS: dict[str, list[str]] = {
    "vid_scene_understanding": [
        r"\b(happening|going on|describe|what does.*(show|depict|contain)|summary|overview|scene(s)?|setting|environment|surroundings|actions?)\b",
    ],
    "vid_object_id": [
        r"\b(what|identify|recognize|name).*(car|vehicle|object|animal|plant|product|thing|item|device|machine|make|brand)\b",
        r"\b(how many).*(cars?|objects?)\b",
        r"\b(color|pick up|raise their hand|disappear|added|removed)\b",
    ],
    "vid_person_id": [
        r"\b(people|persons?|person|man|woman|who|identity|track|face(s)?|enter|walk|go|injured)\b",
        r"\b(how many people)\b",
        r"\b(did the person)\b",
    ],
    "vid_text_ocr": [
        r"\b(written|text|ocr|read|caption|subtitle|lettering|printed|displayed|board|screen|sign|wall|label|paper)\b",
    ],
    "vid_document_analysis": [
        r"\b(document|receipt|invoice|certificate|passport|id card|license|letter|form|contract)\b",
    ],
    "vid_commercial_verification": [
        r"\b(product|brand|packaging|label|commercial|advertisement|counterfeit|authentic|logo)\b",
    ],
    "video_location": [
        r"\b(where|location|place|city|country|region|landmark|architecture|street|store|building|environmental)\b",
    ],
    "video_date_time": [
        r"\b(date|when|day|year|time|timestamp|recorded|calendar|clock)\b",
    ],
    "video_timeline": [
        r"\b(happened|first|before|after|sequence|order|timeline|subsequent|prior|at what point)\b",
    ],
    "video_manipulation": [
        r"\b(edited|spliced|cut|removed|manipulat|tamper|doctored|continuity|forensic|jump cut|speed|slow motion|cropped|blurry|compressed|re-encoded|missing frames|duplicated)\b",
    ],
    "video_ai_detection": [
        r"\b(ai.?generated|synthetic|deepfake|fake|computer.?generated|lip.?sync|voice|audio replaced)\b",
    ],
    "vid_face_manipulation": [
        r"\b(deepfake|face.?swap|face.?replace|facial|manipulated face|synthetic face|lip movement)\b",
    ],
    "aud_av_sync": [
        r"\b(sync|synchron(ized|ization)|out of sync|lip.?sync|audio.?video|timing)\b",
    ],
    "aud_transcription": [
        r"\b(say|said|speech|spoken|transcri|quote|words|language|translate|subtitles)\b",
    ],
    "vid_two_video_comparison": [
        r"\b(two videos|compare|comparison|same|different|between|changed|related|batch)\b",
    ],
    "video_metadata": [
        r"\b(metadata|resolution|codec|fps|frame rate|bitrate|quality|format|dimensions|compression)\b",
    ],
    "video_claim_verification": [
        r"\b(true|claim|verify|verification|actually|support|evidence|genuine|legitimate|contradict|news report|verified|confidence)\b",
    ],
    "video_caption_verification": [
        r"\b(caption|title|miscaption|attribution|context|misleading)\b",
    ],
    "vid_privacy_pii": [
        r"\b(personal information|pii|face|address|id|screen|plate|qr|barcode)\b",
    ],
    "vid_safety_hazard": [
        r"\b(dangerous|hazard|weapon|gun|injured|fire|smoke|flood)\b",
    ],
}

# Display order for planned video checks: executable extraction first (they
# produce the evidence), then semantic capabilities grouped by category.
_VIDEO_CHECK_ORDER = [
    "video_analysis",
    "frame_evidence",
    "audio_transcription",
    "video_metadata",
    "vid_scene_understanding",
    "vid_object_id",
    "vid_person_id",
    "vid_face_manipulation",
    "vid_text_ocr",
    "vid_document_analysis",
    "vid_commercial_verification",
    "video_location",
    "video_date_time",
    "video_timeline",
    "video_manipulation",
    "video_ai_detection",
    "aud_av_sync",
    "aud_transcription",
    "vid_two_video_comparison",
    "video_claim_verification",
    "video_caption_verification",
]


def plan_video_investigation(question: str, *, video_count: int = 1) -> List[dict]:
    """Question-driven evidence plan for video investigations.

    The three executable checks (inspection, frames, transcript) are always
    planned — they are what actually produces extractable evidence and every
    category consumes it. Question-matched semantic capabilities from the video
    catalog are ADDED on top so the plan labels which category the user is
    asking about; they carry intent into the analyzer, not separate checks.
    """
    q = (question or "").strip()

    selected = set(_VIDEO_BASELINE_CHECKS) | {"video_analysis", "frame_evidence"}
    for cap_id, patterns in _VIDEO_INTENT_PATTERNS.items():
        if _intent_matches(q, patterns):
            selected.add(cap_id)

    if _intent_matches(q, [r"\b(happening|shows|in the video|describe|summary)\b"]):
        selected.add("vid_scene_understanding")

    if _intent_matches(q, [
        r"\b(ai.?generated|deepfake|synthetic|computer.?generated)\b",
        r"\b(real|fake|manipulated|edited|authentic|genuine)\b",
    ]):
        selected.add("video_ai_detection")
        selected.add("video_manipulation")
        selected.add("vid_face_manipulation")

    if _intent_matches(q, [r"\b(say|said|speech|transcri|quote)\b"]):
        selected.add("aud_transcription")

    if video_count >= 2 and _intent_matches(q, [
        r"\b(compare|comparison|same|different|between)\b",
    ]):
        selected.add("vid_two_video_comparison")

    if video_count >= 2:
        selected.add("vid_two_video_comparison")

    checks = []
    for cap_id in _VIDEO_CHECK_ORDER:
        if cap_id not in selected or cap_id not in EXECUTABLE_BY_CAP:
            continue
        c = EXECUTABLE_BY_CAP[cap_id]
        checks.append({
            "id": f"req_{len(checks) + 1}",
            "type": c["type"],
            "capability": cap_id,
            "reason": c["name"],
        })
    return checks


def plan_image_investigation(question: str, *, image_count: int = 1, batch: bool = False) -> List[dict]:
    """Question-driven evidence plan for image investigations."""
    q = (question or "").strip()

    if batch or image_count > 2:
        selected = set(IMAGE_BASELINE_CHECKS) | {"batch_investigation", "image_c2pa"}
        if _intent_matches(q, _IMAGE_INTENT_PATTERNS.get("image_reverse_search", [])):
            selected.add("image_reverse_search")
    else:
        # Every image investigation runs the full layered pipeline (L1 metadata
        # → L2 reverse-image → L3 earliest-source → L4 context → L5 manipulation)
        # plus C2PA; intent-matched checks (AI detection, OCR, compare, ...) are
        # ADDED on top rather than replacing the mandated layers.
        selected = set(IMAGE_BASELINE_CHECKS) | set(IMAGE_LAYER_CHECKS) | {"image_c2pa"}
        for cap_id, patterns in _IMAGE_INTENT_PATTERNS.items():
            if _intent_matches(q, patterns):
                selected.add(cap_id)

        if _intent_matches(q, [r"\b(real|fake|ai.?generated|manipulated|photoshopped|authentic|genuine|deepfake)\b"]):
            selected.add("image_reverse_search")
            selected.add("ai_detection")

        if _intent_matches(q, [
            r"\b(is this from|does this show|really show|is this actually|prove that|does this image)\b",
            r"\b(what event|which event|what year|what location|who is in)\b",
        ]):
            selected.add("image_authoritative_search")
            selected.add("image_reverse_search")

        if _intent_matches(q, _IMAGE_INTENT_PATTERNS.get("meme_context", [])):
            selected.add("image_reverse_search")

        if _intent_matches(q, _IMAGE_INTENT_PATTERNS.get("copyright_attribution", [])):
            selected.add("image_reverse_search")
            selected.add("image_c2pa")

    if image_count >= 2:
        selected.add("image_compare")
    if image_count >= 2 and _intent_matches(q, _IMAGE_INTENT_PATTERNS.get("before_after_analysis", [])):
        selected.add("before_after_analysis")

    checks = []
    for cap_id in _IMAGE_CHECK_ORDER:
        if cap_id not in selected or cap_id not in EXECUTABLE_BY_CAP:
            continue
        c = EXECUTABLE_BY_CAP[cap_id]
        checks.append({
            "id": f"req_{len(checks) + 1}",
            "type": c["type"],
            "capability": cap_id,
            "reason": c["name"],
        })
    return checks


def plan_image_layers() -> List[dict]:
    """Deterministic full-layer requirement set for an image investigation
    (see IMAGE_LAYER_CHECKS for the layered order)."""
    checks = []
    for cap_id in IMAGE_LAYER_CHECKS:
        c = EXECUTABLE_BY_CAP.get(cap_id)
        if not c:
            continue
        checks.append({
            "id": f"req_{len(checks) + 1}",
            "type": c["type"],
            "capability": cap_id,
            "reason": c["name"],
        })
    return checks


def plan_evidence_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_claim_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_image_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


def plan_video_requirements(question: str, inputs: List[str]) -> List[dict]:
    return plan_video_investigation(question)


def plan_source_requirements(question: str, inputs: List[str]) -> List[dict]:
    return EvidencePlanner()._plan_fallback(question, inputs)


if __name__ == "__main__":  # self-check
    # baseline is always planned, whatever the question
    cats = {c["capability"] for c in plan_video_investigation("Is the claim in this video true?")}
    assert {"video_analysis", "frame_evidence", "audio_transcription"} <= cats
    # question category adds the matching semantic capability
    assert "video_claim_verification" in cats
    ocr = {c["capability"] for c in plan_video_investigation("What is written on the board?")}
    assert "vid_text_ocr" in ocr and "video_claim_verification" not in ocr
    cmp = {c["capability"] for c in plan_video_investigation("Are these two videos the same?", video_count=2)}
    assert "vid_two_video_comparison" in cmp
    speech = {c["capability"] for c in plan_video_investigation("What does the person say?")}
    assert "aud_transcription" in speech
    # video_question_needs_frames: speech-only skips frames, visuals keep them
    assert video_question_needs_frames("What does the person say?") is False
    assert video_question_needs_frames("What car is shown?") is True
    assert video_question_needs_frames("") is True  # unknown intent keeps frames
    # plans are ordered per _VIDEO_CHECK_ORDER and deduplicated
    caps = [c["capability"] for c in plan_video_investigation("")]
    assert len(caps) == len(set(caps))
    print("planner self-check OK")
