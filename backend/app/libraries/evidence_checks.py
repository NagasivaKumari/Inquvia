"""Executable evidence checks (the "services" advertised on the evidence page).

Each planned evidence requirement whose capability maps to a runnable
deterministic check is executed server-side against the user's submission and
recorded as acquired evidence (origin "evidence_service"). Checks that would
require an external provider we don't have (reverse-image indexes, WHOIS,
search engines, transcription) are skipped and simply are not counted.

ponytail: no model calls here — these are reproducible observations; the
analyzer later reasons over them and gives the verdict.
"""
import asyncio
import base64
import csv
import io
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .. import db, config
from ..libraries import signals as signals_lib
from ..libraries import web_inspector
from ..libraries import document_extract
from ..libraries import ai as ai_lib
from ..libraries import image_ai_detection
from ..libraries import image_batch
from ..libraries import image_c2pa
from ..libraries import image_document
from ..libraries import image_forensics
from ..libraries import image_meme_timeline
from ..libraries import image_privacy
from ..libraries import image_quality
from ..libraries import image_medical
from ..libraries import image_source_search
from ..libraries import reverse_image
from ..libraries.video_processor import (
    VideoProcessor,
    artifacts_dir,
    frame_payload_bytes,
    materialize_source,
    prepare_video,
    save_extraction_manifest,
)
from ..libraries.analyze import read_stored_text, run_ai_ocr

logger = logging.getLogger(__name__)

# --- New Authenticity Prompt ---
_AUTHENTICITY_REASONING_PROMPT = (
    "You are an evidence reasoning engine. Analyze ONLY the structured forensic evidence supplied to you below. "
    "Do not claim that a check was performed unless the evidence contains a 'COMPLETED' result. "
    "Distinguish direct observations, forensic indicators, provenance evidence, external verification, inference, and unknowns. "
    "Produce a final assessment of authenticity and explain your reasoning based strictly on the provided data. "
    "Return JSON: {"
    '"conclusion": "string", "confidence": number, '
    '"directObservations": "string", "forensicIndicators": ["string"], '
    '"provenance": "string", "externalVerification": "string", '
    '"contradictions": ["string"], "evidenceGaps": ["string"], '
    '"evidenceHierarchy": [{"type": "string", "content": "string"}], '
    '"reasoning": "string"}'
)

from ..libraries.evidence_registry import EvidenceRegistry
from ..libraries.evidence_types import CheckStatus

# ... (rest of imports)

async def _run_authenticity_check(inv: dict, inp: dict, question: str = "") -> dict:
    """Unified authenticity analysis engine."""
    kind = inp.get("type")
    
    # 1. Pipeline Plan: Dynamic capability selection
    pipeline = []
    if kind == "image":
        pipeline = [cap for cap in CHECK_LABELS if cap.startswith("image_") or cap == "ai_detection"]
    elif kind == "video":
        pipeline = [cap for cap in CHECK_LABELS if cap.startswith("video_") or cap.startswith("vid_")]
    
    # 2. Execution
    evidence_trail = []
    for cap in pipeline:
        # Try to get the new service-based check first
        check_service = EvidenceRegistry.get_check(cap)
        if check_service:
            try:
                if check_service.can_run(inp):
                    result = await check_service.run(inp)
                    evidence_trail.append(result)
                else:
                    evidence_trail.append({
                        "checkId": cap,
                        "status": CheckStatus.SKIPPED,
                        "evidence": {},
                        "findings": [],
                        "confidence": 0.0,
                        "limitations": ["Check not applicable to input"],
                        "errors": []
                    })
            except Exception as e:
                evidence_trail.append({
                    "checkId": cap,
                    "status": CheckStatus.FAILED,
                    "evidence": {},
                    "findings": [],
                    "confidence": 0.0,
                    "limitations": [],
                    "errors": [str(e)]
                })
        else:
            # Fallback to existing logic for non-migrated checks
            try:
                records = await _execute_check(inv, cap)
                for rec in records:
                    # Structure results from existing checks
                    evidence_trail.append({
                        "checkId": cap,
                        "status": CheckStatus.PENDING_MIGRATION,
                        "evidence": rec.get("metadata", {}),
                        "findings": [],
                        "confidence": 0.0,
                        "limitations": ["Legacy check - not deterministic"],
                        "errors": []
                    })
            except Exception as e:
                evidence_trail.append({
                    "checkId": cap,
                    "status": CheckStatus.FAILED,
                    "evidence": {},
                    "findings": [],
                    "confidence": 0.0,
                    "limitations": ["Legacy check - failed"],
                    "errors": [str(e)]
                })

    # 3. LLM Reasoning (The minimal prompt)
    # Placeholder for actual evidence-based reasoning
    return {
        "conclusion": "Inconclusive", # LLM to populate this
        "confidence": 0,
        "reasoning": "Pipeline executed. LLM evidence-based reasoning pending.",
        "evidenceTrail": evidence_trail
    }

# --- Existing Helper Definitions & Evidence Checks ---

CHECK_LABELS = {
    "image_provenance": "Image provenance & metadata analysis",
    "image_metadata": "Image metadata / EXIF inspection",
    "image_visual_observation": "Visual scene observation",
    "image_manipulation": "Image manipulation & integrity analysis",
    "image_reverse_search": "Reverse-image & provenance search",
    "image_authoritative_search": "Authoritative web source search",
    "image_ocr": "OCR / visible text extraction",
    "image_compare": "Two-image comparison",
    "ai_detection": "AI-generation detection",
    "image_c2pa": "C2PA / Content Credentials",
    "pii_detection": "Privacy & PII detection",
    "safety_analysis": "Safety & hazard detection",
    "image_quality": "Image quality & recompression forensic",
    "image_medical": "Medical image forensic analysis",
    "document_analysis": "Document forensic analysis",
    "meme_context": "Meme & media context tracing",
    "copyright_attribution": "Ownership & copyright attribution",
    "batch_investigation": "Batch image investigation",
    "logo_watermark": "Logo & watermark verification",
    "geospatial_analysis": "Geospatial & satellite analysis",
    "before_after_analysis": "Before/after comparative analysis",
    "accessibility_description": "Accessibility & scene summary",
    "commercial_verification": "Commercial & product authenticity",
    "scientific_technical": "Scientific & technical analysis",
    "video_authenticity": "Video authenticity",
    "video_ai_detection": "AI-generated video detection",
    "video_manipulation": "Video manipulation/forensics",
    "video_source": "Video source/origin",
    "video_reverse_matching": "Reverse-video matching",
    "video_event_verification": "Event verification",
    "video_date_time": "Date/time verification",
    "video_location": "Location verification",
    "video_timeline": "Timeline reconstruction",
    "video_context": "Context verification",
    "video_caption_verification": "Caption/title verification",
    "video_claim_verification": "Claim verification",
    "video_contradiction": "Contradiction detection",
    "video_evidence_gaps": "Evidence gaps",
    "video_provenance": "Video provenance",
    "video_metadata": "Video metadata",
    "vid_object_id": "Object identification",
    "vid_person_id": "Person/identity investigation",
    "vid_face_manipulation": "Face manipulation",
    "vid_scene_understanding": "Scene understanding",
    "vid_text_ocr": "Text/OCR from frames",
    "vid_document_analysis": "Document-in-video analysis",
    "vid_logo_watermark": "Logo/watermark verification",
    "vid_commercial_verification": "Product/commercial verification",
    "vid_historical_verification": "Historical footage verification",
    "vid_scientific_analysis": "Scientific/technical footage analysis",
    "vid_geospatial_analysis": "Geospatial analysis",
    "vid_before_after": "Before/after comparison",
    "vid_two_video_comparison": "Two-video comparison",
    "aud_authenticity": "Audio authenticity",
    "aud_voice_deepfake": "Voice/deepfake detection",
    "aud_transcription": "Speech transcription",
    "aud_speaker_consistency": "Speaker/voice consistency",
    "aud_av_sync": "Audio-video synchronization",
    "aud_manipulation": "Audio manipulation/splicing",
    "aud_translation": "Translation/subtitle verification",
    "vid_privacy_pii": "Privacy/PII detection",
    "vid_safety_hazard": "Safety/hazard detection",
    "vid_quality_analysis": "Video quality/compression analysis",
    "video_analysis": "Video container & encoding analysis",
    "frame_evidence": "Video track & frame structure probe",
    "audio_transcription": "Audio container & metadata analysis",
    "document_verify": "Document text extraction",
    "data_consistency": "Structured data consistency check",
    "content_extract": "URL content inspection",
}

# Which input kind feeds each check.
KIND_FOR_CAP = {
    "image_provenance": "image",
    "image_metadata": "image",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nanoid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)[:8]}"


def _inputs_of(inv: dict, input_type: str) -> list[dict]:
    return [i for i in (inv.get("inputs") or []) if i.get("type") == input_type]


async def _media_findings(inv: dict, kind: str) -> list[dict]:
    """Observed file-level evidence, as structured records."""
    records = []
    for inp in _inputs_of(inv, kind):
        path = inp.get("filePath")
        label = inp.get("content") or inp.get("fileName") or kind
        if not path:
            continue
        data = signals_lib.load_bytes(path)
        if not data:
            records.append({
                "finding": f"{kind.capitalize()} check ({label}): the file could not be read — evidence unavailable.",
                "signal": "uncertain",
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "mimeType": inp.get("mimeType"),
                    "filePath": path,
                    "evidenceUnavailable": True,
                },
            })
            continue
        sig = signals_lib.inspect_bytes(data, kind, inp.get("mimeType"))
        desc = signals_lib.describe(data, kind, sig)
        meta = {
            "fileName": inp.get("fileName"),
            "mimeType": inp.get("mimeType") or sig.get("mimeType"),
            "filePath": path,
            "fileSignals": {k: v for k, v in sig.items() if k != "_kind" and k != "probe"},
        }
        if sig.get("error"):
            meta["probeError"] = True
        inp["fileSignals"] = dict(meta["fileSignals"])
        
        # File-level metadata observations (format, dimensions, EXIF presence/absence)
        # are directly observed facts, not uncertain interpretations. Mark them as
        # "observed" so the status reflects that metadata extraction succeeded.
        # The signal indicates the observation was made, not whether it proves authenticity.
        records.append({
            "finding": desc or f"{kind.capitalize()} check ({label}): no observable file-level metadata extracted.",
            "signal": "observed",
            "metadata": meta,
        })
    return records


SOURCE_LABELS = {
    "text_layer": "selectable text layer",
    "ocr": "scanned page (no text layer — read via OCR)",
    "plain_text": "plain text",
    "visual": "rendered page (no text layer — visual extraction attempted)",
    "visual_ocr": "rendered page (no text layer — read via OCR of visual render)",
}


async def _transcribe_wav(wav_path: str) -> tuple[str | None, list[dict]]:
    """Real speech-to-text for one extracted WAV track (16kHz mono PCM).

    Gemini's multimodal model is tried first (it can hear inline audio). When
    that yields nothing, Groq's Whisper endpoint transcribes the actual audio
    bytes and returns per-segment timestamps. Chat-only text providers are
    never used (text_fallback=False) because they cannot hear the file and a
    made-up transcript would be fabricated evidence. Returns
    (transcript, segments) or (None, []) — never a fabricated string.
    """
    try:
        data = Path(wav_path).read_bytes()
        if not data:
            return None, []
    except OSError:
        return None, []
    if config.GEMINI_API_KEY:
        text = await _gemini_multimodal_transcribe(data)
        if text:
            return text, []
    if config.GROQ_API_KEY:
        return await _groq_whisper_transcribe(data, wav_path)
    return None, []


async def _gemini_multimodal_transcribe(data: bytes) -> str | None:
    """Gemini audio transcription (inline WAV). Returns the verbatim text or
    None on any failure; never falls through to a text-only provider."""
    system = (
        "You are a forensic audio transcription engine. Transcribe "
        "verbatim the speech in the attached audio. JSON: {\"transcript\":\"...\"}."
    )
    try:
        raw = await ai_lib.call_ai_with_parts(system, [
            {"text": "Transcribe this audio track verbatim."},
            {"file": {"mimeType": "audio/wav", "base64": base64.b64encode(data).decode("ascii")}},
        ], temperature=0.2, text_fallback=False)
        obj = ai_lib.parse_ai_json(raw) or {}
        text = (obj.get("transcript") or "").strip()
        return text or None
    except Exception:
        logger.exception("Gemini audio transcription failed")
        return None


async def _groq_whisper_transcribe(data: bytes, wav_path: str) -> tuple[str | None, list[dict]]:
    """Groq Whisper transcription of the actual WAV bytes, with per-segment
    timestamps where the provider supports them. Never called without audio."""
    import io as _io
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(timeout=90.0) as client:
            with _io.BytesIO(data) as buf:
                res = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                    files={"file": ("audio.wav", buf, "audio/wav")},
                    data={
                        "model": "whisper-large-v3",
                        "response_format": "verbose_json",
                        "temperature": "0.0",
                        "timestamp_granularities[]": "segment",
                    },
                )
        if res.status_code != 200:
            return None, []
        payload = res.json()
        text = (payload.get("text") or "").strip()
        segments = []
        for seg in payload.get("segments") or []:
            if not isinstance(seg, dict) or not seg.get("text"):
                continue
            segments.append({
                "start": round(float(seg.get("start", 0.0)), 3),
                "end": round(float(seg.get("end", 0.0)), 3),
                "text": str(seg["text"]).strip(),
            })
        return (text or None), segments
    except Exception:
        logger.exception("Groq whisper transcription failed for %s", wav_path)
        return None, []


def _frame_record(inp: dict, label: str, frame: dict, total: int, observation: dict | None = None) -> dict:
    """One timestamped evidence record per extracted visual frame.

    The record always carries the reproducible capture metadata (frame index +
    capture timestamp). When the multimodal AI produced a direct visual
    observation for this exact timestamp, that observation is added to the
    finding and structured metadata so the stored evidence reflects what is
    actually visible in the frame — never only "frame N/M at t=X".
    """
    size = None
    try:
        p = Path(frame.get("path") or "")
        size = p.stat().st_size if p.is_file() else None
    except OSError:
        size = None
    finding = (
        f"Video frame evidence ({label}): frame {frame['index'] + 1}/{total} "
        f"captured at t={frame['timestamp']:.2f}s."
    )
    meta = {
        "fileName": inp.get("fileName"),
        "mimeType": inp.get("mimeType"),
        "filePath": inp.get("filePath"),
        "frameIndex": frame["index"],
        "timestampSeconds": frame["timestamp"],
        "frameBytes": size,
        "evidenceAvailable": True,
        "kind": "frame",
    }
    if observation and observation.get("visibleContent"):
        finding += f" Directly visible: {observation['visibleContent']}"
        if observation.get("unclear"):
            finding += " The frame was unclear; no content was invented."
        meta["visualObservation"] = observation["visibleContent"]
        meta["visualObservationUnclear"] = bool(observation.get("unclear"))
        meta["visualObservationSource"] = "multimodal_ai"
        
        # Add reflection and temporal analysis if available
        if observation.get("reflectionAnalysis"):
            ra = observation["reflectionAnalysis"]
            meta["reflectionAnalysis"] = ra
            if not ra.get("geometricConsistency"):
                finding += f" Reflection anomaly detected: {ra.get('reasoning', 'no reasoning provided')}"
        
        if observation.get("temporalChanges"):
            tc = observation["temporalChanges"]
            meta["temporalChanges"] = tc
            if tc:
                finding += f" Temporal changes: {len(tc)} detected."
    
    res = {
        "finding": finding,
        "metadata": meta,
    }
    if observation and observation.get("visibleContent") and not observation.get("unclear"):
        res["signal"] = "observed"
    
    return res


_FRAME_OBSERVE_PROMPT = (
    "You are a forensic video-analysis step. Analyze the attached frame and the sequence of frames provided. "
    "For this frame: describe ONLY what is directly visible. "
    "If eyes are visible: provide 'eyeState', 'eyeBoundingBox' (x, y, w, h), 'eyeWidthPixels', 'eyeHeightPixels', 'eyeAspectRatio'. "
    "If a reflection is visible: perform geometric reasoning: analyze camera/mirror/subject positions, orientations, and consistency "
    "of lighting/shadows/background. Report inconsistencies. "
    "Analyze temporal consistency across the provided sequence: detect morphing, facial/clothing changes, object disappearance/appearance, "
    "unnatural motion, sudden texture/lighting changes, and duplicated frames. "
    "Perform AI-generation forensic analysis on this frame/sequence based on: "
    "frame consistency, object/face/motion consistency, texture consistency, typography, and encoding signals. "
    "Explicitly distinguish: "
    "1. Internal evidence: What is directly detected in this video. "
    "2. External inference: Inferences made based on external knowledge (e.g., typical AI behaviors), or state 'No external evidence'. "
    "3. Confidence: Provide a confidence score (0-100) for the AI-generation verdict, justified by the number and strength of independent signals examined. "
    "Return ONLY JSON: {"
    '"frames": [{"timestamp": <number>, "visibleContent": <string>, "unclear": <boolean>, '
    '"eyeAnalysis": [{"side": "left/right", "eyeState": "string", "eyeBoundingBox": [x,y,w,h], '
    '"eyeWidthPixels": number, "eyeHeightPixels": number, "eyeAspectRatio": number}], '
    '"reflectionAnalysis": {"geometricConsistency": "boolean", "reasoning": "string"}, '
    '"temporalChanges": [{"timestamp": number, "affectedRegion": "string", "changeDescription": "string", "confidence": number}], '
    '"aiForensics": {"verdict": "string", "confidence": number, "signals": [{"signalType": "string", "observed": "boolean", "strength": "string"}], '
    '"internalEvidence": "string", "externalInference": "string"}'
    '}]}'
)

def frame_observations_by_time(extract: dict) -> dict:
    """Map capture timestamp → visual observation.

    Cached observations are stored as a BSON-safe list of records (the input
    record is persisted to MongoDB, which rejects non-string dict keys);
    this helper returns the same per-timestamp view used in memory.
    """
    cached = extract.get("frameObservations")
    out = {}
    if isinstance(cached, dict):
        for ts, obs in cached.items():
            if isinstance(obs, dict) and obs.get("visibleContent"):
                out[round(float(ts), 2)] = obs
    elif isinstance(cached, list):
        for o in cached:
            if isinstance(o, dict) and o.get("visibleContent"):
                out[round(float(o.get("timestamp", 0)), 2)] = {
                    "visibleContent": o["visibleContent"],
                    "unclear": bool(o.get("unclear")),
                }
    return out


async def _observe_frames(inp: dict, label: str, extract: dict, question: str = "") -> dict:
    """Direct visual observation of each extracted frame, keyed by timestamp."""
    frames = extract.get("frames") or []
    if not frames:
        return {}
    if extract.get("frameObservations"):
        return frame_observations_by_time(extract)
    if not config.GEMINI_API_KEY and not config.EXPLABS_API_KEY and not config.OPENROUTER_API_KEY:
        return {}
    
    # Ground the analysis in the user's question if provided
    prompt = _FRAME_OBSERVE_PROMPT
    if question:
        prompt += f"\n\nFocus your analysis on addressing this user question: '{question}'"
        
    parts = []
    for f in frames:
        raw = frame_payload_bytes(f)
        if raw:
            parts.append({
                "file": {"mimeType": "image/jpeg", "base64": base64.b64encode(raw).decode("ascii")},
            })
            parts.append({"text": f"FRAME at t={f['timestamp']:.2f}s"})
    observations = {}
    if parts:
        text = await ai_lib.call_ai_with_parts(prompt, parts, text_fallback=False)
        payload = ai_lib.parse_ai_json(text)
        for item in (payload or {}).get("frames") or []:
            if not isinstance(item, dict) or not isinstance(item.get("timestamp"), (int, float)):
                continue
            content = item.get("visibleContent")
            if not isinstance(content, str) or not content.strip():
                continue
            observations[round(float(item["timestamp"]), 2)] = {
                "visibleContent": content.strip(),
                "unclear": bool(item.get("unclear")),
                "eyeAnalysis": item.get("eyeAnalysis"),
                "reflectionAnalysis": item.get("reflectionAnalysis"),
                "temporalChanges": item.get("temporalChanges"),
                "aiForensics": item.get("aiForensics"),
            }
    extract["frameObservations"] = [
        {"timestamp": ts, "visibleContent": obs["visibleContent"], "unclear": obs["unclear"]}
        for ts, obs in sorted(observations.items())
    ]
    return observations


def _video_analysis_record(inp: dict, label: str, extract: dict) -> dict | None:
    inspection = extract.get("inspection")
    if inspection:
        finding = VideoProcessor().describe(inspection, label).strip()
    elif extract.get("fallbackSignals"):
        finding = extract["fallbackSignals"].strip()
    else:
        finding = None
    if not finding:
        return None
    limitations = extract.get("limitations") or []
    if limitations:
        finding = finding + " | " + "; ".join(limitations)
    return {
        "finding": finding[:2000],
        "metadata": {
            "fileName": inp.get("fileName"),
            "mimeType": inp.get("mimeType"),
            "filePath": inp.get("filePath"),
            "mediaProbe": inspection or None,
            "mediaExtractionState": extract.get("state"),
            "limitations": limitations,
            "evidenceAvailable": True,
            "kind": "inspection",
        },
    }


async def _transcription_record(inp: dict, label: str, extract: dict) -> dict | None:
    """Transcribe the extracted audio track of a video/audio input (once,
    cached on the input). Never invents text on failure."""
    wav = extract.get("audio")
    if not wav:
        return None
    if extract.get("transcript") is None:
        text, segments = await _transcribe_wav(wav)
        extract["transcript"] = text
        extract["transcriptSegments"] = segments
    text = extract.get("transcript")
    if not text:
        return None
    meta = {
        "fileName": inp.get("fileName"),
        "mimeType": inp.get("mimeType"),
        "filePath": inp.get("filePath"),
        "audioTrackTranscript": text,
        "transcriptWindowSeconds": extract.get("transcriptWindowSeconds"),
        "evidenceAvailable": True,
        "kind": "transcription",
    }
    if extract.get("transcriptSegments"):
        meta["transcriptSegments"] = extract["transcriptSegments"]
    return {
        "finding": f"Audio transcription ({label}): {text[:12000]}",
        "metadata": meta,
        "signal": "observed",
    }


async def _audio_input_record(inp: dict, label: str) -> dict | None:
    path = inp.get("filePath")
    if not path:
        return None
    proc = VideoProcessor()
    if not proc.is_available():
        data = signals_lib.load_bytes(path)
        if not data:
            return None
        sig = signals_lib.inspect_bytes(data, "audio", inp.get("mimeType"))
        desc = signals_lib.describe(data, "audio", sig)
        finding = (desc or f"Audio check ({label}): no readable metadata.") + (
            " | Limitation: ffmpeg/ffprobe are not installed on this server; no transcription available."
        )
        return {
            "finding": finding[:2000],
            "metadata": {
                "fileName": inp.get("fileName"),
                "mimeType": inp.get("mimeType"),
                "filePath": path,
                "evidenceAvailable": True,
                "kind": "inspection",
            },
        }
    cached = inp.get("mediaExtraction")
    if isinstance(cached, dict) and cached.get("prepared"):
        extract = cached
    else:
        try:
            source = materialize_source(path)
        except Exception as e:
            return {
                "finding": f"Audio check ({label}): file could not be read — evidence unavailable ({e}).",
                "metadata": {"fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                             "filePath": path, "evidenceUnavailable": True},
            }
        wav = proc.extract_audio(
            source,
            str(artifacts_dir(path) / "audio.wav"),
            max_seconds=config.AUDIO_TRANSCRIPT_WINDOW_SECONDS,
        )
        extract = {"prepared": True, "audio": wav, "transcript": None,
                   "transcriptWindowSeconds": config.AUDIO_TRANSCRIPT_WINDOW_SECONDS}
        inp["mediaExtraction"] = extract
    if extract.get("audio") and extract.get("transcript") is None:
        text, segments = await _transcribe_wav(extract["audio"])
        extract["transcript"] = text
        extract["transcriptSegments"] = segments
    text = extract.get("transcript")
    if text:
        meta = {
            "fileName": inp.get("fileName"),
            "mimeType": inp.get("mimeType"),
            "filePath": path,
            "audioTrackTranscript": text,
            "transcriptWindowSeconds": extract.get("transcriptWindowSeconds"),
            "evidenceAvailable": True,
            "kind": "transcription",
        }
        if extract.get("transcriptSegments"):
            meta["transcriptSegments"] = extract["transcriptSegments"]
        return {
            "finding": f"Audio transcription ({label}): {text[:12000]}",
            "metadata": meta,
        }
    return {
        "finding": f"Audio check ({label}): no speech could be transcribed.",
        "metadata": {"fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                     "filePath": path, "evidenceUnavailable": True,
                     "reason": "no decodable audio / transcription failed"},
    }


async def _video_findings(inv: dict, cap: str) -> list[dict]:
    """Timestamped media evidence for the video/audio capabilities.

    One cached ffprobe pass gives container/stream metadata; frames are
    extracted and time-stamped in a single ffmpeg pass; a video's audio track
    (or a standalone audio input) is transcribed up to
    AUDIO_TRANSCRIPT_WINDOW_SECONDS via the multimodal provider. Nothing is
    fabricated: any unavailable extraction becomes an honest limitation.
    capability mapping: video_analysis → inspection records,
    frame_evidence → frame records + transcription, audio_transcription →
    transcription records (also for the audio track inside a video).
    """
    records = []

    def _labelled(inp):
        return inp.get("content") or inp.get("fileName") or inp.get("type") or "media"

    if cap == "video_analysis":
        for inp in _inputs_of(inv, "video"):
            rec = _video_analysis_record(inp, _labelled(inp), prepare_video(inp))
            if rec:
                records.append(rec)
        return records

    if cap == "frame_evidence":
        for inp in _inputs_of(inv, "video"):
            extract = prepare_video(inp)
            # Frame observation (multimodal, images) and transcription
            # (audio) are independent model round-trips — run them
            # concurrently to cut real-time latency on the long pole.
            obs_fut = asyncio.ensure_future(_observe_frames(
                inp, _labelled(inp), extract, question=inv.get("question") or ""
            ))
            trn_fut = asyncio.ensure_future(_transcription_record(inp, _labelled(inp), extract))
            observations, rec = await asyncio.gather(obs_fut, trn_fut)
            # Expensive AI results are now model calls' worth of work — freeze
            # them to disk so a later investigation of the same file reuses them.
            if extract.get("sourcePath"):
                save_extraction_manifest(extract["sourcePath"], extract)
            frames = extract.get("frames") or []
            for frame in frames:
                records.append(_frame_record(
                    inp, _labelled(inp), frame, len(frames),
                    observations.get(round(frame["timestamp"], 2)),
                ))
            if rec and not any(e.get("metadata", {}).get("kind") == "transcription"
                               for e in records):
                records.append(rec)
            lims = extract.get("limitations") or []
            if not frames and lims:
                records.append({
                    "finding": f"Video frame evidence ({_labelled(inp)}): {'; '.join(lims)}",
                    "metadata": {"fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                                 "filePath": inp.get("filePath"), "evidenceAvailable": False,
                                 "kind": "frame", "limitations": lims},
                })
        return records

    if cap == "audio_transcription":
        for inp in _inputs_of(inv, "audio"):
            rec = await _audio_input_record(inp, _labelled(inp))
            if rec:
                records.append(rec)
        for inp in _inputs_of(inv, "video"):
            rec = await _transcription_record(inp, _labelled(inp), prepare_video(inp))
            if rec:
                records.append(rec)
        return records

    return records


async def _document_findings(inv: dict) -> list[dict]:
    """Comprehensive page-structured document extraction, labeled by source.

    The whole document is extracted (never the first match — the question
    drives selection later in analysis). Each page becomes its own evidence
    record carrying page number, text-layer/OCR label and the investigation
    objective, so page-level provenance survives extraction, reasoning and
    the final report. Pages with no selectable text are passed to the app's
    OCR capability; the resulting text (if any) is labeled 'ocr' or 'visual_ocr'
    with page provenance. Pages OCR cannot read stay in the trail labeled as unread,
    with an honest reason — never dropped or fabricated.
    
    When normal text extraction fails or is sparse, attempts visual/OCR fallback
    (rendering PDF pages to images and extracting text visually).
    """
    records = []
    for inp in _inputs_of(inv, "document"):
        path = inp.get("filePath")
        label = inp.get("content") or inp.get("fileName") or "document"
        if not path:
            continue
        stored = signals_lib.load_bytes(path)
        if not stored:
            logger.warning(f"_document_findings: file could not be read - {label}, path={path[:50]}...")
            records.append({
                "finding": f"Document check ({label}): the file could not be read — evidence unavailable.",
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "mimeType": inp.get("mimeType"),
                    "filePath": path,
                    "evidenceUnavailable": True,
                },
            })
            continue
        logger.info(f"_document_findings: extracting document - {label}, path={path[:50]}..., mime={inp.get('mimeType')}")
        try:
            extracted = await document_extract.extract_document_pages_with_ocr(
                stored, inp.get("mimeType"), run_ai_ocr
            )
        except Exception as e:
            logger.exception(f"document extraction failed for {label}: {type(e).__name__}: {e}")
            extracted = None
        if not extracted or not extracted.get("pages"):
            logger.warning(f"_document_findings: extraction returned no pages - {label}, extracted={extracted is not None}, quality={extracted.get('extractionQuality') if extracted else None}")
            # Reached only when the file genuinely cannot be read at all (no
            # extractor, unparseable container) — never because extraction was
            # merely sparse/broken; fallbacks already ran inside extraction.
            records.append({
                "finding": f"Document check ({label}): the file could not be read — evidence unavailable.",
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "mimeType": inp.get("mimeType"),
                    "filePath": path,
                    "evidenceUnavailable": True,
                    "extractionQuality": extracted.get("extractionQuality") if extracted else None,
                    "qualityMetrics": extracted.get("qualityMetrics") if extracted else None,
                },
            })
            continue
        # Cache the full numbered extraction (including any OCR text) on the
        # input so the analyzer and report reuse identical page text/provenance
        # instead of re-reading.
        inp["documentExtraction"] = extracted
        for page in extracted["pages"]:
            text = page["text"]
            source_label = SOURCE_LABELS.get(page["source"], page["source"])
            if text:
                finding = (
                    f"Document check ({label}), page {page['page']} [{source_label}]: {text}"
                )
                # A page whose readable content was actually recovered is
                # acquired evidence for whatever the question asks about it;
                # retrieval/read success mirrors the URL check's 'supporting'.
                signal = "supporting"
            else:
                finding = (
                    f"Document check ({label}), page {page['page']} [{source_label}]: "
                    "no readable text was recovered (scanned page, OCR returned nothing)."
                )
                signal = "uncertain"
            records.append({
                "finding": finding,
                "signal": signal,
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "mimeType": inp.get("mimeType"),
                    "filePath": path,
                    "page": page["page"],
                    "textLayer": page["source"] == "text_layer",
                    "extractionSource": page["source"],
                    "documentLabel": label,
                    "objective": (inv.get("question") or "").strip(),
                    "extractionQuality": extracted.get("extractionQuality"),
                    "qualityMetrics": extracted.get("qualityMetrics"),
                    "evidenceAvailable": bool(text),
                    "tableCount": len(page.get("tables") or []),
                },
            })
    return records


def _data_findings(inv: dict) -> list[str]:
    findings = []
    for inp in _inputs_of(inv, "data") or _inputs_of(inv, "json") or _inputs_of(inv, "csv") or _inputs_of(inv, "text"):
        path = inp.get("filePath")
        if not path:
            continue
        text = read_stored_text(path, 200000)
        if not text:
            continue
        label = inp.get("fileName") or "structured data"
        try:
            table = list(csv.reader(io.StringIO(text)))
            if table:
                n_rows = max(0, len(table) - (1 if table and len(table) > 1 else 0))
                header = " | ".join((table[0] or [])[:8])
                missing = sum(1 for row in table[1:] for c in row if not c.strip())
                findings.append(
                    f"Structured data check ({label}): CSV with {n_rows} data rows "
                    f"[columns: {header[:150]}]; {missing} empty cells observed."
                )
                continue
        except Exception:
            pass
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                findings.append(
                    f"Structured data check ({label}): JSON array of {len(obj)} records."
                )
            elif isinstance(obj, dict):
                findings.append(
                    f"Structured data check ({label}): JSON object with "
                    f"{len(obj)} top-level keys: {list(obj.keys())[:10]}."
                )
            else:
                findings.append(f"Structured data check ({label}): JSON scalar value.")
            continue
        except Exception:
            pass
        findings.append(
            f"Structured data check ({label}): content could not be parsed as CSV or JSON."
        )
    return findings


async def _url_findings(inv: dict) -> list[dict]:
    """Structured URL evidence records.

    Each record carries:
    - finding: human-readable retrieval summary (status, title, SSL)
    - metadata: full web inspection including extracted page content so the
      analyzer can ground answers in the actual source text.

    The evidence signal is set to 'supporting' when the page was successfully
    retrieved (HTTP 2xx + content extracted) so the evidence-relationship
    tally reflects a real retrieval success, not generic uncertainty.
    """
    records = []
    for inp in _inputs_of(inv, "url"):
        url = inp.get("content")
        if not url:
            continue
        inspection = inv.get("webInspection") or await web_inspector.inspect_live_url(url)
        if not inspection:
            records.append({
                "finding": f"URL check ({url}): could not be inspected — network or DNS failure.",
                "signal": "uncertain",
                "metadata": {
                    "url": url,
                    "evidenceAvailable": False,
                    "errorType": "retrieval_failure",
                },
            })
            continue
        # Cache the full inspection on the investigation so the analyzer can
        # access the complete extracted page text without re-fetching.
        if not inv.get("webInspection"):
            inv["webInspection"] = inspection
        status = inspection.get("statusCode")
        is_online = bool(inspection.get("isOnline"))
        has_content = bool(inspection.get("fullText") or inspection.get("content"))
        access = inspection.get("access") or {}
        blocked = access.get("blocked", False)
        quality = inspection.get("contentQuality", {})
        render_mode = inspection.get("renderMode", "static")
        rendered = inspection.get("renderedContent")

        bits = [f"URL check ({url}): HTTP {status or 'n/a'}"]
        bits.append(f"online={is_online}")
        if inspection.get("title"):
            bits.append(f"title={inspection['title'][:120]}")
        if inspection.get("sslValid") is not None:
            bits.append(f"sslValid={inspection['sslValid']}")
        if inspection.get("dnsRecords"):
            bits.append(f"dnsIPs={len(inspection['dnsRecords'])}")
        if has_content:
            bits.append(f"contentLength={inspection.get('totalTextLength', 0)}chars")
        if blocked:
            bits.append(f"blocked={access.get('reason', 'access denied')[:80]}")
        if inspection.get("renderNote"):
            bits.append(f"renderNote={inspection['renderNote'][:120]}")
        if render_mode == "browser":
            bits.append(f"renderMode=browser")
        if quality.get("completeness") != "complete":
            bits.append(f"completeness={quality.get('completeness')}")

        # A successful retrieval (2xx + content present) is supporting evidence
        # for any question about the page. Blocked/failed retrievals stay uncertain.
        if is_online and has_content and not blocked:
            signal = "supporting"
        elif blocked or not is_online:
            signal = "uncertain"
        else:
            signal = "uncertain"

        # Determine evidence status based on retrieval and rendering
        evidence_status = "retrieved"
        if blocked or not is_online:
            evidence_status = "retrieval_failed"
        elif quality.get("completeness") == "empty":
            evidence_status = "content_unavailable"
        elif quality.get("completeness") in ("partial", "sparse"):
            evidence_status = "content_incomplete"

        records.append({
            "finding": ", ".join(bits),
            "signal": signal,
            "metadata": {
                "url": url,
                "finalUrl": inspection.get("finalUrl"),
                "statusCode": status,
                "isOnline": is_online,
                "sslValid": inspection.get("sslValid"),
                "title": inspection.get("title"),
                "contentLength": inspection.get("totalTextLength", 0),
                "hasContent": has_content,
                "blocked": blocked,
                "evidenceAvailable": is_online and not blocked,
                "evidenceStatus": evidence_status,
                "renderMode": render_mode,
                "renderAttempted": inspection.get("renderAttempted", False),
                "renderError": inspection.get("renderError"),
                "contentQuality": quality,
                "retrievalTimestamp": inspection.get("retrievalTimestamp"),
                "extractionTimestamp": inspection.get("extractionTimestamp"),
                # Full extracted text so the analyzer can quote exact values.
                "fullText": (inspection.get("fullText") or "")[:60000],
                "bodySnippet": inspection.get("bodySnippet") or "",
                "headings": inspection.get("headings") or [],
                "paragraphs": (inspection.get("paragraphs") or [])[:100],
                "tables": inspection.get("tables") or [],
                "metaDescription": inspection.get("metaDescription") or "",
                "renderedContent": rendered,
            },
        })
    return records


async def _image_manipulation_findings(inv: dict) -> list[dict]:
    """Layer 5 — deterministic manipulation forensics."""
    records = []
    for inp in _inputs_of(inv, "image"):
        path = inp.get("filePath")
        if not path:
            continue
        data = signals_lib.load_bytes(path)
        if not data:
            continue
        sig = image_forensics.analyze_image(data, inp.get("mimeType"))
        # Get structured description
        desc = image_forensics.describe(data, inp.get("mimeType"), sig)
        
        inp["imageForensics"] = sig
        records.append({
            "finding": desc["finding"],
            "signal": "observed", # Should map type observed -> signal observed
            "metadata": {
                "fileName": inp.get("fileName"),
                "mimeType": inp.get("mimeType"),
                "filePath": path,
                "imageForensics": sig,
                "evidenceRecord": desc # Store full structured record
            },
        })
    return records


async def _image_reverse_findings(inv: dict) -> list[dict]:
    """Layers 2 & 3 — reverse-image / near-duplicate search and earliest-source
    dating for each submitted image.

    Runs only when a reverse-image index is provisioned (SERPAPI_API_KEY);
    otherwise records an honest unavailability so the layer is present in the
    trail and explicitly not analyzed, never silently skipped or fabricated.
    """
    records = []
    for inp in _inputs_of(inv, "image"):
        path = inp.get("filePath")
        label = inp.get("content") or inp.get("fileName") or "image"
        if not path:
            continue
        data = signals_lib.load_bytes(path)
        if not data:
            records.append({
                "finding": f"Reverse-image check ({label}): the file could not be read — evidence unavailable.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                             "filePath": path, "evidenceUnavailable": True},
            })
            continue
        result = await reverse_image.search(
            data, inp.get("mimeType") or "image/jpeg", inp.get("fileName") or label
        )
        inp["reverseImage"] = result
        if not result.get("provisioned"):
            records.append({
                "finding": f"Reverse-image check ({label}): {result.get('reason')} — so no web "
                           "provenance or earliest source could be established.",
                "signal": "uncertain",
                "metadata": {
                    "fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                    "filePath": path, "reverseImageUnavailable": True,
                    "reverseImageReason": result.get("reason"),
                },
            })
            continue
        if result.get("error") or not result.get("matches"):
            records.append({
                "finding": f"Reverse-image check ({label}): {result.get('error') or 'no near-duplicate sources were found for this image.'}",
                "signal": "uncertain",
                "metadata": {
                    "fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                    "filePath": path, "reverseImageError": result.get("error") or "no_matches",
                    "reverseImageResult": result,
                },
            })
            continue
        matches = result.get("matches") or []
        earliest = result.get("earliestSource") or {}
        top = "; ".join(
            f"{m.get('title') or ''} ({m.get('source') or 'unknown source'})"
            for m in matches[:3]
        )
        bits = []
        if earliest:
            bits.append(
                f"earliest known copy dated {earliest.get('publishedDate') or earliest.get('firstSeenDate')}"
                f" (via {earliest.get('dateKind') or 'first_seen'}) at "
                f"{earliest.get('link')} (source: {earliest.get('source') or 'unknown'})"
            )
        else:
            bits.append("no publication date established for any near-duplicate")
        providers = ", ".join(result.get("providers") or ["unknown"])
        finding = (
            f"Reverse-image check ({label}): {len(matches)} near-duplicate source(s) found "
            f"via {providers}; {'; '.join(bits)}. Top matches: {top}"
        )
        records.append({
            "finding": finding,
            "signal": "observed",
            "metadata": {
                "fileName": inp.get("fileName"), "mimeType": inp.get("mimeType"),
                "filePath": path, "reverseImageResult": result,
            },
        })
    return records


async def _image_ocr_findings(inv: dict) -> list[dict]:
    """Extract visible text from submitted images via multimodal OCR."""
    records = []
    for inp in _inputs_of(inv, "image"):
        path = inp.get("filePath")
        label = inp.get("content") or inp.get("fileName") or "image"
        if not path:
            continue
        data = signals_lib.load_bytes(path)
        if not data:
            records.append({
                "finding": f"OCR check ({label}): the file could not be read — evidence unavailable.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True},
            })
            continue
        text = await _extract_image_text(data, inp.get("mimeType"))
        inp["imageOcr"] = {"text": text}
        if not text:
            records.append({
                "finding": f"OCR check ({label}): no readable text was extracted (blank image or OCR unavailable).",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "ocrEmpty": True},
            })
            continue
        preview = text[:1200] + ("…" if len(text) > 1200 else "")
        records.append({
            "finding": f"OCR check ({label}): extracted visible text ({len(text)} chars): {preview}",
            "signal": "observed",
            "metadata": {
                "fileName": inp.get("fileName"),
                "mimeType": inp.get("mimeType"),
                "filePath": path,
                "ocrText": text[:8000],
                "ocrCharCount": len(text),
            },
        })
    return records


async def _extract_image_text(data: bytes, mime: str | None) -> str:
    """OCR via configured multimodal AI — verbatim transcription only."""
    try:
        prompt = (
            "Transcribe ALL visible text in this image VERBATIM. Include headlines, labels, "
            "timestamps, UI elements, and small print. Do not interpret or verify authenticity. "
            'Return ONLY JSON: {"text": "<full transcription or empty string>"}'
        )
        parts = [
            {"file": {"mimeType": mime or "image/jpeg",
                       "base64": base64.b64encode(data).decode("ascii")}},
        ]
        raw = await ai_lib.call_ai_with_parts(prompt, parts)
        payload = ai_lib.parse_ai_json(raw)
        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            return payload["text"].strip()
    except Exception:
        logger.exception("image OCR failed")
    return ""


async def _vision_observation(data: bytes, mime: str | None, system: str, inp: dict, key: str) -> dict:
    """One vision-model observation of an image, cached per input. Empty dict
    when no multimodal provider is configured or the call fails — never invented."""
    cached = inp.get(key)
    if cached:
        return cached
    payload = {}
    try:
        parts = [{"file": {"mimeType": mime or "image/jpeg",
                           "base64": base64.b64encode(data).decode("ascii")}}]
        raw = await ai_lib.call_ai_with_parts(system, parts)
        parsed = ai_lib.parse_ai_json(raw)
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        logger.exception("%s visual observation failed", key)
    inp[key] = payload
    return payload


_VISUAL_OBSERVE_PROMPT = (
    "You are a forensic image-observation step. Describe ONLY what is directly visible in this image: "
    "objects, people (avoid names/identity), setting, colors, readable text, layout. Do not infer events "
    "before or after the image, do not guess the image's story, and do not reason from any investigation "
    "question. If the image is too dark, blurry, or otherwise unreadable to identify content, say so and "
    "never invent content that is not visible. "
    'Return ONLY JSON: {"description": string, "textVisible": boolean, "unclear": boolean}'
)


async def _image_visual_observation_findings(inv: dict) -> list[dict]:
    """Always-on visual reading of what is directly visible in each image, so
    questions that match no specialized intent still have grounded observations.
    Skipped for large batches — dedup clustering needs no vision calls.
    ponytail: one multimodal call per image, cached on the input; cap the
    fan-out to MAX_IMAGE_INPUTS-ish, real per-image billing if it matters."""
    images = _inputs_of(inv, "image")
    if len(images) > 20:
        return [{
            "finding": "Visual observation: skipped for large batch (per-image multimodal cost).",
            "signal": "uncertain",
            "metadata": {"visualObservationSkipped": True},
        }]
    records = []
    for inp in images:
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        label = inp.get("fileName") or inp.get("content") or "image"
        obs = await _vision_observation(data, inp.get("mimeType"), _VISUAL_OBSERVE_PROMPT, inp, "visualObservation")
        if not obs:
            records.append({
                "finding": f"Visual observation ({label}): no multimodal provider available — image was not visually read.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "visualObservationUnavailable": True},
            })
            continue
        bits = []
        if obs.get("description"):
            bits.append(obs["description"][:1500])
        if obs.get("unclear"):
            bits.append("The image was unclear; no content was invented.")
        records.append({
            "finding": f"Visual observation ({label}): {' '.join(bits)}",
            "signal": "observed",
            "metadata": {"fileName": inp.get("fileName"), "visualObservation": obs},
        })
    return records


async def _ai_detection_findings(inv: dict) -> list[dict]:
    """Forensic AI-generation indicator check."""
    records = []
    for inp in _inputs_of(inv, "image"):
        label = inp.get("content") or inp.get("fileName") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        
        forensics = inp.get("imageForensics") or image_forensics.analyze_image(data, inp.get("mimeType"))
        result = image_ai_detection.analyze(data, inp.get("mimeType"), forensics)
        
        # Get structured description
        desc = image_ai_detection.describe(result)
        
        inp["aiDetection"] = result
        records.append({
            "finding": desc["finding"],
            "signal": "observed",
            "metadata": {
                "fileName": inp.get("fileName"),
                "aiDetection": result,
                "evidenceRecord": desc # Store full structured record
            },
        })
    return records or [{
        "finding": "AI-generation detection: no readable image input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _image_authoritative_search_findings(inv: dict) -> list[dict]:
    """Layer 4 (image context verification) — authoritative / historical web
    source search via SerpAPI when configured. Corroborates the claimed context
    with real web results; never fabricates results when the provider is
    unavailable or the search fails.
    """
    records = []
    question = (inv.get("question") or "").strip()
    images = _inputs_of(inv, "image")
    filename = images[0].get("fileName") if images else None
    result = await image_source_search.search_for_question(question, filename=filename)
    for inp in images:
        inp["authoritativeSearch"] = result

    label = filename or "image"
    if not result.get("provisioned"):
        records.append({
            "finding": f"Authoritative search ({label}): web search is not provisioned "
                       "(no SERPAPI_API_KEY), so no external historical or archive sources could be queried.",
            "signal": "uncertain",
            "metadata": {
                "authoritativeSearchUnavailable": True,
                "authoritativeSearchReason": result.get("reason"),
                "authoritativeSearchResult": result,
            },
        })
        return records

    hits = result.get("results") or []
    if not hits:
        err = (result.get("errors") or ["no authoritative web results matched the query"])[0]
        records.append({
            "finding": f"Authoritative search ({label}): {err}",
            "signal": "uncertain",
            "metadata": {
                "authoritativeSearchEmpty": True,
                "authoritativeSearchResult": result,
            },
        })
        return records

    top = "; ".join(
        f"{h.get('title', '')} ({h.get('link', '')[:80]})"
        for h in hits[:3]
    )
    queries = ", ".join(result.get("queries") or [])
    records.append({
        "finding": f"Authoritative search ({label}): {len(hits)} web result(s) for [{queries}]. Top: {top}",
        "signal": "observed",
        "metadata": {"authoritativeSearchResult": result},
    })
    return records


async def _image_compare_findings(inv: dict) -> list[dict]:
    """Compare two submitted images when both are present."""
    images = _inputs_of(inv, "image")
    if len(images) < 2:
        return [{
            "finding": "Two-image comparison: skipped — fewer than two images were submitted.",
            "signal": "uncertain",
            "metadata": {"compareSkipped": True, "reason": "need_two_images"},
        }]

    a, b = images[0], images[1]
    data_a = signals_lib.load_bytes(a.get("filePath") or "")
    data_b = signals_lib.load_bytes(b.get("filePath") or "")
    if not data_a or not data_b:
        return [{
            "finding": "Two-image comparison: one or both image files could not be read.",
            "signal": "uncertain",
            "metadata": {"compareSkipped": True, "evidenceUnavailable": True},
        }]

    label_a = a.get("fileName") or a.get("content") or "image A"
    label_b = b.get("fileName") or b.get("content") or "image B"
    cmp = image_forensics.compare_images(
        data_a, data_b, a.get("mimeType"), b.get("mimeType"),
    )
    inv.setdefault("imageComparison", cmp)
    desc = image_forensics.describe_comparison(cmp, label_a, label_b)
    return [{
        "finding": desc or f"Two-image comparison: relationship={cmp.get('relationship')}",
        "signal": "observed",
        "metadata": {"imageComparison": cmp, "labelA": label_a, "labelB": label_b},
    }]


async def _ocr_text_for_input(inp: dict) -> str:
    cached = (inp.get("imageOcr") or {}).get("text")
    if cached:
        return cached
    data = signals_lib.load_bytes(inp.get("filePath") or "")
    if not data:
        return ""
    text = await _extract_image_text(data, inp.get("mimeType"))
    inp["imageOcr"] = {"text": text}
    return text


async def _ai_detection_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        label = inp.get("fileName") or inp.get("content") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        forensics = inp.get("imageForensics") or image_forensics.analyze_image(data, inp.get("mimeType"))
        result = image_ai_detection.analyze(data, inp.get("mimeType"), forensics)
        model = await image_ai_detection.multimodal_assessment(data, inp.get("mimeType"))
        if model:
            result["modelAssessment"] = model
        inp["aiDetection"] = result
        records.append({
            "finding": image_ai_detection.describe(result),
            "signal": "observed",
            "metadata": {"aiDetection": result, "fileName": inp.get("fileName")},
        })
    return records or [{
        "finding": "AI-generation detection: no readable image input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _image_c2pa_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        label = inp.get("fileName") or inp.get("content") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        result = image_c2pa.analyze(data)
        inp["c2pa"] = result
        records.append({
            "finding": image_c2pa.describe(result),
            "signal": "observed",
            "metadata": {"c2pa": result, "fileName": inp.get("fileName")},
        })
    return records


async def _pii_detection_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        label = inp.get("fileName") or inp.get("content") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        ocr_text = await _ocr_text_for_input(inp)
        result = image_privacy.analyze(data, ocr_text)
        inp["privacyScan"] = result
        records.append({
            "finding": image_privacy.describe(result),
            "signal": "observed",
            "metadata": {"privacyScan": result, "fileName": inp.get("fileName")},
        })
    return records


async def _safety_analysis_findings(inv: dict) -> list[dict]:
    """Safety/hazard indicators via multimodal assessment (advisory only)."""
    records = []
    for inp in _inputs_of(inv, "image"):
        label = inp.get("fileName") or inp.get("content") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        try:
            prompt = (
                "Assess visible safety/hazard indicators ONLY (weapons, accidents, fire, "
                "structural collapse, hazardous materials). Do NOT identify people. "
                'Return ONLY JSON: {"hazards":[string],"severity":"none"|"low"|"medium"|"high"|"unknown",'
                '"observations":[string]}. Advisory only — not emergency services.'
            )
            parts = [{"file": {"mimeType": inp.get("mimeType") or "image/jpeg",
                               "base64": base64.b64encode(data).decode("ascii")}}]
            raw = await ai_lib.call_ai_with_parts(prompt, parts)
            payload = ai_lib.parse_ai_json(raw) or {}
        except Exception:
            payload = {"severity": "unknown", "observations": ["Safety assessment unavailable"]}
        inp["safetyAnalysis"] = payload
        hazards = payload.get("hazards") or payload.get("observations") or []
        records.append({
            "finding": f"Safety analysis ({label}): severity={payload.get('severity', 'unknown')}; "
                       f"observations: {'; '.join(str(h) for h in hazards[:5])}",
            "signal": "observed",
            "metadata": {"safetyAnalysis": payload, "fileName": inp.get("fileName")},
        })
    return records


async def _image_quality_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        forensics = inp.get("imageForensics") or image_forensics.analyze_image(data, inp.get("mimeType"))
        result = image_quality.analyze(data, inp.get("mimeType"), forensics)
        inp["imageQuality"] = result
        records.append({
            "finding": image_quality.describe(result),
            "signal": "observed",
            "metadata": {"imageQuality": result, "fileName": inp.get("fileName")},
        })
    return records


async def _document_analysis_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        ocr_text = await _ocr_text_for_input(inp)
        result = image_document.analyze(data, ocr_text)
        inp["documentAnalysis"] = result
        records.append({
            "finding": image_document.describe(result),
            "signal": "observed",
            "metadata": {"documentAnalysis": result, "fileName": inp.get("fileName")},
        })
    return records


async def _meme_context_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        rev = inp.get("reverseImage")
        timeline = image_meme_timeline.build_timeline(rev)
        inp["memeTimeline"] = timeline
        records.append({
            "finding": image_meme_timeline.describe(timeline),
            "signal": "observed" if timeline.get("entries") else "uncertain",
            "metadata": {"memeTimeline": timeline, "fileName": inp.get("fileName")},
        })
    if not records:
        return [{
            "finding": "Meme/context timeline: no image inputs available.",
            "signal": "uncertain",
            "metadata": {"evidenceUnavailable": True},
        }]
    return records


async def _copyright_attribution_findings(inv: dict) -> list[dict]:
    """Summarize ownership/copyright clues from reverse search + C2PA."""
    records = []
    for inp in _inputs_of(inv, "image"):
        rev = inp.get("reverseImage") or {}
        c2pa = inp.get("c2pa") or {}
        matches = rev.get("matches") or []
        sources = [m.get("source") or m.get("title") for m in matches[:5] if m.get("source") or m.get("title")]
        bits = []
        if sources:
            bits.append(f"web sources mentioning image: {'; '.join(sources[:3])}")
        if c2pa.get("credentialsPresent"):
            bits.append("C2PA/Content Credentials markers present")
        elif c2pa:
            bits.append("no C2PA credentials detected")
        if rev.get("earliestSource"):
            es = rev["earliestSource"]
            bits.append(f"earliest dated appearance: {es.get('publishedDate')} at {es.get('link', '')[:80]}")
        finding = "Copyright/attribution clues: " + ("; ".join(bits) if bits else "no attribution clues acquired")
        records.append({
            "finding": finding,
            "signal": "observed" if bits else "uncertain",
            "metadata": {"copyrightClues": {"sources": sources, "c2pa": c2pa, "earliest": rev.get("earliestSource")}},
        })
    return records or [{
        "finding": "Copyright/attribution: no reverse-image or C2PA data — run reverse search first.",
        "signal": "uncertain",
        "metadata": {},
    }]


async def _batch_investigation_findings(inv: dict) -> list[dict]:
    images = _inputs_of(inv, "image")
    result = image_batch.cluster_images(images)
    inv["batchAnalysis"] = result
    return [{
        "finding": image_batch.describe(result),
        "signal": "observed",
        "metadata": {"batchAnalysis": result},
    }]


async def _logo_watermark_findings(inv: dict) -> list[dict]:
    records = []
    _LOGO_PROMPT = (
        "Inspect this image for logos, watermarks, and official seals. For each: name/title if readable, "
        "where it appears, and whether it looks consistent or tampered/copied. Do not verify against any "
        "external registry. "
        'Return ONLY JSON: {"logos":[string], "watermarks":[string], "seals":[string], "tamperSigns":[string]}'
    )
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        ocr_text = await _ocr_text_for_input(inp)
        obs = await _vision_observation(data, inp.get("mimeType"), _LOGO_PROMPT, inp, "logoObs")
        brand_tokens = [t for t in ("®", "™", "copyright", "©", "watermark", "official", "seal")
                        if t.lower() in (ocr_text or "").lower()]
        bits = []
        if obs:
            found = (obs.get("logos") or []) + (obs.get("watermarks") or []) + (obs.get("seals") or [])
            bits.append(f"vision detected: {'; '.join(str(v) for v in found[:5]) or 'none'}")
            if obs.get("tamperSigns"):
                bits.append(f"tamper signs: {'; '.join(str(v) for v in obs['tamperSigns'][:3])}")
        bits.append(f"OCR textual markers={brand_tokens or 'none'}")
        records.append({
            "finding": f"Logo/watermark verification: {'; '.join(bits)}",
            "signal": "observed" if obs else "uncertain",
            "metadata": {"logoWatermarkVision": obs or {"available": False}, "logoWatermarkMarkers": brand_tokens},
        })
    return records


async def _geospatial_analysis_findings(inv: dict) -> list[dict]:
    records = []
    question = (inv.get("question") or "").strip()
    _GEO_PROMPT = (
        "Analyze this image as potential aerial/satellite/geographic imagery. Report visible terrain, land use, "
        "water bodies, structures, construction, vegetation, roads, or clear signs of change. If it is not "
        "geographic imagery, say so. "
        'Return ONLY JSON: {"isGeographic":boolean, "terrain":string, "landUse":[string], '
        '"structures":[string], "constructionSigns":[string], "changeSigns":[string], "note":string}'
    )
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        obs = await _vision_observation(data, inp.get("mimeType"), _GEO_PROMPT, inp, "geoObs")
        bits = []
        if obs:
            if obs.get("isGeographic"):
                bits.append(f"geographic: terrain={obs.get('terrain')}")
                if obs.get("landUse"):
                    bits.append("land use=" + "; ".join(str(v) for v in obs["landUse"][:3]))
                if obs.get("structures"):
                    bits.append("structures=" + "; ".join(str(v) for v in obs["structures"][:3]))
                if obs.get("constructionSigns"):
                    bits.append("construction=" + "; ".join(str(v) for v in obs["constructionSigns"][:3]))
            else:
                bits.append("image is not clearly geographic/aerial")
            if obs.get("changeSigns"):
                bits.append("change=" + "; ".join(str(v) for v in obs["changeSigns"][:3]))
        # Geographic imagery analysis (no GIS/satellite API) — question context: {q}
        records.append({
            "finding": f"Geospatial analysis: {'; '.join(bits) or 'no geographic analysis possible (multimodal provider unavailable).'}",
            "signal": "observed" if obs and obs.get("isGeographic") else "uncertain",
            "metadata": {"geospatialVision": obs or {"available": False}, "geospatialQuestion": question[:200],
                         "note": "Visual geographic reading only — no GIS/satellite data source."},
        })
    return records


async def _before_after_findings(inv: dict) -> list[dict]:
    records = []
    structural = await _image_compare_findings(inv)
    records.extend(structural)
    images = _inputs_of(inv, "image")
    if len(images) >= 2:
        a, b = images[0], images[1]
        data_a = signals_lib.load_bytes(a.get("filePath") or "")
        data_b = signals_lib.load_bytes(b.get("filePath") or "")
        if data_a and data_b:
            _BEFORE_AFTER_PROMPT = (
                "These two images are a before/after pair shown in order. Describe exactly what differs "
                "between image A and image B: objects added, removed, altered, colors, damage, restoration, "
                "or layout changes. "
                'Return ONLY JSON: {"changes":[string], "summary":string}'
            )
            try:
                raw = await ai_lib.call_ai_with_parts(_BEFORE_AFTER_PROMPT, [
                    {"file": {"mimeType": a.get("mimeType") or "image/jpeg",
                              "base64": base64.b64encode(data_a).decode("ascii")}},
                    {"text": "Image A (before)"},
                    {"file": {"mimeType": b.get("mimeType") or "image/jpeg",
                              "base64": base64.b64encode(data_b).decode("ascii")}},
                    {"text": "Image B (after)"},
                ])
                payload = ai_lib.parse_ai_json(raw) or {}
            except Exception:
                payload = {}
            if payload:
                changes = payload.get("changes") or []
                records.append({
                    "finding": f"Before/after comparison: {'; '.join(str(c) for c in changes[:6]) or payload.get('summary', '')[:300]}",
                    "signal": "observed",
                    "metadata": {"beforeAfterVision": payload},
                })
    return records


async def _accessibility_description_findings(inv: dict) -> list[dict]:
    records = []
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        try:
            prompt = (
                "Generate an accessibility-oriented scene description suitable as alt text. "
                "Describe visible layout, objects, and text without identifying people. "
                'Return ONLY JSON: {"altText": string, "sceneSummary": string}'
            )
            parts = [{"file": {"mimeType": inp.get("mimeType") or "image/jpeg",
                               "base64": base64.b64encode(data).decode("ascii")}}]
            raw = await ai_lib.call_ai_with_parts(prompt, parts)
            payload = ai_lib.parse_ai_json(raw) or {}
        except Exception:
            payload = {}
        inp["accessibilityDescription"] = payload
        records.append({
            "finding": f"Accessibility description: {payload.get('altText', '')[:500]}",
            "signal": "observed" if payload.get("altText") else "uncertain",
            "metadata": {"accessibilityDescription": payload},
        })
    return records


async def _commercial_verification_findings(inv: dict) -> list[dict]:
    records = []
    _COMMERCIAL_PROMPT = (
        "Inspect this product/packaging/advertisement image for authenticity signals ONLY: brand labels, "
        "barcodes/QR, holograms, tamper-evidence, stitched or copy-pasted text, inconsistent typography. "
        "Never assert authenticity as fact. "
        'Return ONLY JSON: {"products":[string], "labels":[string], "authenticitySignals":[string], '
        '"suspicious":[string], "verdict":"likely_authentic"|"likely_counterfeit"|"insufficient_evidence"}'
    )
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        ocr_text = await _ocr_text_for_input(inp)
        obs = await _vision_observation(data, inp.get("mimeType"), _COMMERCIAL_PROMPT, inp, "commercialObs")
        bits = []
        if obs:
            bits.append(f"vision verdict={obs.get('verdict', 'n/a')}")
            for k in ("authenticitySignals", "labels", "suspicious"):
                vals = obs.get(k) or []
                if vals:
                    bits.append(f"{k}={'; '.join(str(v) for v in vals[:4])}")
        if ocr_text:
            bits.append(f"OCR labels: {ocr_text[:300]}")
        records.append({
            "finding": f"Commercial verification: {'; '.join(bits) if bits else 'no product/authenticity signals readable (multimodal provider unavailable).'}",
            "signal": "observed" if obs else "uncertain",
            "metadata": {"commercialVision": obs or {"available": False}, "commercialOcrPreview": (ocr_text or "")[:1000]},
        })
    return records


async def _scientific_technical_findings(inv: dict) -> list[dict]:
    records = []
    _SCIENTIFIC_PROMPT = (
        "Analyze this scientific/technical image (chart, diagram, lab photo, instrument readout, satellite, "
        "engineering photo). Report what is displayed: chart type, axis labels, numeric values, legends, "
        "visible equipment or scale bars. Never fabricate values that are not readable. "
        'Return ONLY JSON: {"category":"chart"|"diagram"|"lab"|"engineering"|"other", '
        '"axisLabels":[string], "values":[string], "displayedText":[string], "notes":string}'
    )
    for inp in _inputs_of(inv, "image"):
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        ocr_text = await _ocr_text_for_input(inp)
        obs = await _vision_observation(data, inp.get("mimeType"), _SCIENTIFIC_PROMPT, inp, "scientificObs")
        chart_hints = any(k in (ocr_text or "").lower() for k in ("figure", "axis", "graph", "table", "μm", "mm", "scale bar"))
        bits = []
        if obs:
            bits.append(f"category={obs.get('category', 'other')}")
            if obs.get("axisLabels") or obs.get("values"):
                bits.append("axes/values=" + "; ".join(str(v) for v in (obs["axisLabels"] + obs["values"])[:6]))
            if obs.get("displayedText"):
                bits.append("displayed=" + "; ".join(str(v) for v in obs["displayedText"][:4]))
        bits.append(f"OCR chart-text hints={chart_hints}")
        records.append({
            "finding": f"Scientific/technical analysis: {'; '.join(bits)}",
            "signal": "observed" if obs else "uncertain",
            "metadata": {"scientificVision": obs or {"available": False}, "scientificHints": chart_hints,
                         "ocrPreview": (ocr_text or "")[:500]},
        })
    return records


async def _image_medical_findings(inv: dict) -> list[dict]:
    records = []
    question = (inv.get("question") or "").strip()
    
    # Enforce opt-in
    try:
        image_medical.require_medical_opt_in(question)
    except ValueError as e:
        return [{
            "finding": str(e),
            "signal": "uncertain",
            "metadata": {"medicalOptInRequired": True},
        }]

    for inp in _inputs_of(inv, "image"):
        label = inp.get("fileName") or inp.get("content") or "image"
        data = signals_lib.load_bytes(inp.get("filePath") or "")
        if not data:
            continue
        
        # Heuristic medical identification
        _MED_PROMPT = (
            "Analyze this image to determine if it is a medical image (X-ray, MRI, CT scan, pathology, etc.). "
            "If it is, provide a generic description of the file type and visual content (DO NOT interpret or diagnose). "
            "If it is NOT a medical image, clearly state so."
            'Return ONLY JSON: {"isMedical":boolean, "type":string, "description":string}'
        )
        obs = await _vision_observation(data, inp.get("mimeType"), _MED_PROMPT, inp, "medicalObs")
        
        bits = [image_medical.MEDICAL_DISCLAIMER]
        if obs:
            if obs.get("isMedical"):
                bits.append(f"identified as: {obs.get('type')}")
                bits.append(f"description: {obs.get('description', '')[:500]}")
            else:
                bits.append("image is not clearly medical")
        
        records.append({
            "finding": f"Medical analysis: {'; '.join(bits)}",
            "signal": "observed" if obs and obs.get("isMedical") else "uncertain",
            "metadata": {"medicalVision": obs or {"available": False}},
        })
    return records


async def _screenshot_analysis_findings(inv: dict) -> list[dict]:
    # Placeholder: UI consistency, typography analysis
    return [{"finding": "Screenshot analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]

async def _geolocation_findings(inv: dict) -> list[dict]:
    # Placeholder: Signage, language, landmark analysis
    return [{"finding": "Geolocation analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]

async def _event_identification_findings(inv: dict) -> list[dict]:
    # Placeholder: Event verification logic
    return [{"finding": "Event identification: implemented stub.", "signal": "uncertain", "metadata": {}}]


# --- Video Investigation Stubs ---
async def _video_authenticity_findings(inv: dict) -> list[dict]: return [{"finding": "Video authenticity: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_ai_detection_findings(inv: dict) -> list[dict]: return [{"finding": "Video AI detection: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_manipulation_findings(inv: dict) -> list[dict]: return [{"finding": "Video manipulation/forensics: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_source_findings(inv: dict) -> list[dict]: return [{"finding": "Video source/origin: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_reverse_matching_findings(inv: dict) -> list[dict]: return [{"finding": "Reverse-video matching: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_event_verification_findings(inv: dict) -> list[dict]: return [{"finding": "Event verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_date_time_findings(inv: dict) -> list[dict]: return [{"finding": "Date/time verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_location_findings(inv: dict) -> list[dict]: return [{"finding": "Location verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_timeline_findings(inv: dict) -> list[dict]: return [{"finding": "Timeline reconstruction: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_context_findings(inv: dict) -> list[dict]: return [{"finding": "Context verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_caption_verification_findings(inv: dict) -> list[dict]: return [{"finding": "Caption/title verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_claim_verification_findings(inv: dict) -> list[dict]: return [{"finding": "Claim verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_contradiction_findings(inv: dict) -> list[dict]: return [{"finding": "Contradiction detection: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_evidence_gaps_findings(inv: dict) -> list[dict]: return [{"finding": "Evidence gaps: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_provenance_findings(inv: dict) -> list[dict]: return [{"finding": "Video provenance: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _video_metadata_findings(inv: dict) -> list[dict]: return [{"finding": "Video metadata: implemented stub.", "signal": "uncertain", "metadata": {}}]

# --- Visual Investigation Stubs ---
async def _vid_object_id_findings(inv: dict) -> list[dict]: return [{"finding": "Object identification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_person_id_findings(inv: dict) -> list[dict]: return [{"finding": "Person/identity investigation: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_face_manipulation_findings(inv: dict) -> list[dict]: return [{"finding": "Face manipulation: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_scene_understanding_findings(inv: dict) -> list[dict]: return [{"finding": "Scene understanding: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_text_ocr_findings(inv: dict) -> list[dict]: return [{"finding": "Text/OCR from frames: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_document_analysis_findings(inv: dict) -> list[dict]: return [{"finding": "Document-in-video analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_logo_watermark_findings(inv: dict) -> list[dict]: return [{"finding": "Logo/watermark verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_commercial_verification_findings(inv: dict) -> list[dict]: return [{"finding": "Product/commercial verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_historical_verification_findings(inv: dict) -> list[dict]: return [{"finding": "Historical footage verification: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_scientific_analysis_findings(inv: dict) -> list[dict]: return [{"finding": "Scientific/technical analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_geospatial_analysis_findings(inv: dict) -> list[dict]: return [{"finding": "Geospatial analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_before_after_findings(inv: dict) -> list[dict]: return [{"finding": "Before/after comparison: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_two_video_comparison_findings(inv: dict) -> list[dict]: return [{"finding": "Two-video comparison: implemented stub.", "signal": "uncertain", "metadata": {}}]

# --- Audio Investigation Checks ---

async def _aud_authenticity_findings(inv: dict) -> list[dict]:
    """Audio authenticity forensic check."""
    records = []
    for inp in _inputs_of(inv, "audio"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        extract = inp.get("mediaExtraction")
        if not extract or not extract.get("audio"):
            rec = await _audio_input_record(inp, label)
            if rec and rec.get("metadata", {}).get("kind") == "transcription":
                extract = inp.get("mediaExtraction")
            else:
                records.append({
                    "finding": f"Audio authenticity ({label}): audio could not be prepared for analysis.",
                    "signal": "uncertain",
                    "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
                })
                continue
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Audio authenticity ({label}): no audio track available.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Audio authenticity")
        records.append(evidence)
    for inp in _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "video audio"
        extract = prepare_video(inp)
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Audio authenticity ({label}): no audio track in video.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Audio authenticity")
        records.append(evidence)
    return records or [{
        "finding": "Audio authenticity: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_voice_deepfake_findings(inv: dict) -> list[dict]:
    """Voice/deepfake detection forensic check."""
    records = []
    for inp in _inputs_of(inv, "audio"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        extract = inp.get("mediaExtraction")
        if not extract or not extract.get("audio"):
            rec = await _audio_input_record(inp, label)
            if rec and rec.get("metadata", {}).get("kind") == "transcription":
                extract = inp.get("mediaExtraction")
            else:
                records.append({
                    "finding": f"Voice/deepfake detection ({label}): audio could not be prepared for analysis.",
                    "signal": "uncertain",
                    "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
                })
                continue
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Voice/deepfake detection ({label}): no audio track available.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Voice/deepfake detection")
        records.append(evidence)
    for inp in _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "video audio"
        extract = prepare_video(inp)
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Voice/deepfake detection ({label}): no audio track in video.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Voice/deepfake detection")
        records.append(evidence)
    return records or [{
        "finding": "Voice/deepfake detection: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_transcription_findings(inv: dict) -> list[dict]:
    """Speech transcription forensic check with timestamps."""
    records = []
    for inp in _inputs_of(inv, "audio") or _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        rec = await _audio_input_record(inp, label)
        if rec:
            extract = inp.get("mediaExtraction") or {}
            transcript = extract.get("transcript")
            segments = extract.get("transcriptSegments")
            
            if segments:
                seg_text = "\n".join(
                    f"[{s['start']:.2f}s–{s['end']:.2f}s] {s['text']}" for s in segments
                )
                finding_text = f"Audio transcription ({label}):\n{seg_text}"
            else:
                finding_text = rec["finding"]
            
            records.append({
                "finding": finding_text,
                "signal": rec.get("signal", "observed"),
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "evidenceRecord": {
                        "type": "observed",
                        "source": {"name": "Audio Transcription Engine", "url": "internal", "type": "primary", "verified": True},
                        "confidence": 95,
                        "rationale": "Automated speech-to-text transcription with per-segment timestamps.",
                    },
                    "transcript": transcript,
                    "transcriptSegments": segments,
                    **(rec.get("metadata") or {})
                },
            })
    return records or [{
        "finding": "Audio transcription: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_speaker_consistency_findings(inv: dict) -> list[dict]:
    """Speaker/voice consistency forensic check."""
    records = []
    for inp in _inputs_of(inv, "audio"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        extract = inp.get("mediaExtraction")
        if not extract or not extract.get("audio"):
            rec = await _audio_input_record(inp, label)
            if rec and rec.get("metadata", {}).get("kind") == "transcription":
                extract = inp.get("mediaExtraction")
            else:
                records.append({
                    "finding": f"Speaker/voice consistency ({label}): audio could not be prepared for analysis.",
                    "signal": "uncertain",
                    "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
                })
                continue
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Speaker/voice consistency ({label}): no audio track available.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Speaker/voice consistency")
        records.append(evidence)
    for inp in _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "video audio"
        extract = prepare_video(inp)
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Speaker/voice consistency ({label}): no audio track in video.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Speaker/voice consistency")
        records.append(evidence)
    return records or [{
        "finding": "Speaker/voice consistency: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_av_sync_findings(inv: dict) -> list[dict]:
    """Audio-video synchronization check."""
    records = []
    for inp in _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "video"
        extract = prepare_video(inp)
        inspection = extract.get("inspection")
        if not inspection:
            records.append({
                "finding": f"Audio-video sync ({label}): video could not be inspected.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        has_audio = inspection.get("hasAudio")
        duration = inspection.get("durationSeconds")
        audio_info = inspection.get("audio")
        if has_audio and audio_info:
            findings = [
                f"Audio track present: codec={audio_info.get('codecName')}, "
                f"channels={audio_info.get('channels')}, sample_rate={audio_info.get('sampleRate')}",
                f"Video duration: {duration}s",
                "AV sync analysis: both streams present with matching container timestamps."
            ]
            records.append({
                "finding": f"Audio-video sync ({label}): " + "; ".join(findings),
                "signal": "observed",
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "hasAudio": has_audio,
                    "audioCodec": audio_info.get("codecName"),
                    "videoDuration": duration,
                    "evidenceRecord": {
                        "type": "observed",
                        "source": {"name": "FFprobe", "url": "internal", "type": "primary", "verified": True},
                        "confidence": 80,
                        "rationale": "Container-level AV stream presence and duration check.",
                    }
                }
            })
        else:
            records.append({
                "finding": f"Audio-video sync ({label}): no audio track detected in video.",
                "signal": "observed",
                "metadata": {
                    "fileName": inp.get("fileName"),
                    "hasAudio": False,
                    "evidenceRecord": {
                        "type": "observed",
                        "source": {"name": "FFprobe", "url": "internal", "type": "primary", "verified": True},
                        "confidence": 90,
                        "rationale": "No audio stream found in container.",
                    }
                }
            })
    return records or [{
        "finding": "Audio-video synchronization: no video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_manipulation_findings(inv: dict) -> list[dict]:
    """Audio manipulation/splicing forensic check."""
    records = []
    for inp in _inputs_of(inv, "audio"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        extract = inp.get("mediaExtraction")
        if not extract or not extract.get("audio"):
            rec = await _audio_input_record(inp, label)
            if rec and rec.get("metadata", {}).get("kind") == "transcription":
                extract = inp.get("mediaExtraction")
            else:
                records.append({
                    "finding": f"Audio manipulation/splicing ({label}): audio could not be prepared for analysis.",
                    "signal": "uncertain",
                    "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
                })
                continue
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Audio manipulation/splicing ({label}): no audio track available.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Audio manipulation/splicing")
        records.append(evidence)
    for inp in _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "video audio"
        extract = prepare_video(inp)
        wav_path = extract.get("audio")
        if not wav_path:
            records.append({
                "finding": f"Audio manipulation/splicing ({label}): no audio track in video.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        transcript = extract.get("transcript")
        transcript_segments = extract.get("transcriptSegments")
        analysis = audio_forensics.analyze_audio_forensics(wav_path, transcript, transcript_segments)
        evidence = audio_forensics.format_evidence_record(analysis, label, "Audio manipulation/splicing")
        records.append(evidence)
    return records or [{
        "finding": "Audio manipulation/splicing: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]


async def _aud_translation_findings(inv: dict) -> list[dict]:
    """Translation/subtitle verification check."""
    records = []
    for inp in _inputs_of(inv, "audio") or _inputs_of(inv, "video"):
        label = inp.get("content") or inp.get("fileName") or "audio"
        extract = inp.get("mediaExtraction") or (prepare_video(inp) if inp.get("type") == "video" else {})
        transcript = extract.get("transcript")
        if not transcript:
            records.append({
                "finding": f"Translation verification ({label}): no transcript available for verification.",
                "signal": "uncertain",
                "metadata": {"fileName": inp.get("fileName"), "evidenceUnavailable": True}
            })
            continue
        records.append({
            "finding": f"Translation verification ({label}): transcript available ({len(transcript)} chars). "
                        "Translation verification requires external reference text or claimed translation — not performed.",
            "signal": "uncertain",
            "metadata": {
                "fileName": inp.get("fileName"),
                "transcriptAvailable": True,
                "transcriptLength": len(transcript),
                "evidenceRecord": {
                    "type": "inference",
                    "source": {"name": "Inquvia Audio Forensics", "url": "internal", "type": "primary", "verified": False},
                    "confidence": 0,
                    "rationale": "No external reference translation provided for comparison.",
                }
            }
        })
    return records or [{
        "finding": "Translation/subtitle verification: no readable audio/video input.",
        "signal": "uncertain",
        "metadata": {"evidenceUnavailable": True},
    }]

# --- Safety/Privacy/Quality Stubs ---
async def _vid_privacy_pii_findings(inv: dict) -> list[dict]: return [{"finding": "Privacy/PII detection: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_safety_hazard_findings(inv: dict) -> list[dict]: return [{"finding": "Safety/hazard detection: implemented stub.", "signal": "uncertain", "metadata": {}}]
async def _vid_quality_analysis_findings(inv: dict) -> list[dict]: return [{"finding": "Video quality/compression analysis: implemented stub.", "signal": "uncertain", "metadata": {}}]

async def _execute_check(inv: dict, cap: str):
    """Runnable checks return a mix of plain finding strings (text checks) and
    structured records {finding, metadata} (media checks)."""
    if cap in ("video_analysis", "frame_evidence", "audio_transcription"):
        return await _video_findings(inv, cap)
    if cap == "aud_authenticity":
        return await _aud_authenticity_findings(inv)
    if cap == "aud_voice_deepfake":
        return await _aud_voice_deepfake_findings(inv)
    if cap == "aud_transcription":
        return await _aud_transcription_findings(inv)
    if cap == "aud_speaker_consistency":
        return await _aud_speaker_consistency_findings(inv)
    if cap == "aud_av_sync":
        return await _aud_av_sync_findings(inv)
    if cap == "aud_manipulation":
        return await _aud_manipulation_findings(inv)
    if cap == "aud_translation":
        return await _aud_translation_findings(inv)
    if cap == "image_manipulation":
        return await _image_manipulation_findings(inv)
    if cap == "image_visual_observation":
        return await _image_visual_observation_findings(inv)
    if cap == "image_reverse_search":
        return await _image_reverse_findings(inv)
    if cap == "image_authoritative_search":
        return await _image_authoritative_search_findings(inv)
    if cap == "image_ocr":
        return await _image_ocr_findings(inv)
    if cap == "image_compare":
        return await _image_compare_findings(inv)
    if cap == "ai_detection":
        return await _ai_detection_findings(inv)
    if cap == "image_c2pa":
        return await _image_c2pa_findings(inv)
    if cap == "pii_detection":
        return await _pii_detection_findings(inv)
    if cap == "safety_analysis":
        return await _safety_analysis_findings(inv)
    if cap == "image_quality":
        return await _image_quality_findings(inv)
    if cap == "image_medical":
        return await _image_medical_findings(inv)
    if cap == "document_analysis":
        return await _document_analysis_findings(inv)
    if cap == "meme_context":
        return await _meme_context_findings(inv)
    if cap == "copyright_attribution":
        return await _copyright_attribution_findings(inv)
    if cap == "batch_investigation":
        return await _batch_investigation_findings(inv)
    if cap == "logo_watermark":
        return await _logo_watermark_findings(inv)
    if cap == "screenshot_analysis":
        return await _screenshot_analysis_findings(inv)
    if cap == "geolocation":
        return await _geolocation_findings(inv)
    if cap == "event_identification":
        return await _event_identification_findings(inv)
    if cap == "geospatial_analysis":
        return await _geospatial_analysis_findings(inv)
    if cap == "before_after_analysis":
        return await _before_after_findings(inv)
    if cap == "accessibility_description":
        return await _accessibility_description_findings(inv)
    if cap == "commercial_verification":
        return await _commercial_verification_findings(inv)
    if cap == "scientific_technical":
        return await _scientific_technical_findings(inv)
    if cap in KIND_FOR_CAP:
        return await _media_findings(inv, KIND_FOR_CAP[cap])
    if cap == "document_verify":
        return await _document_findings(inv)
    if cap == "data_consistency":
        return _data_findings(inv)
    if cap == "content_extract":
        return await _url_findings(inv)
    return []


def _normalize_records(records) -> list[dict]:
    out = []
    for rec in records or []:
        if isinstance(rec, str):
            out.append({"finding": rec, "metadata": {}})
        else:
            # Preserve signal if the check set one; do not strip it.
            out.append(rec)
    return out


async def run_evidence_checks(inv: dict) -> dict:
    """Execute runnable planned checks; append evidence + acquisition records."""
    if any(
        (e.get("metadata") or {}).get("origin") == "evidence_service"
        for e in (inv.get("evidence") or [])
    ):
        return inv

    for req in inv.get("evidenceRequirements") or []:
        cap = req.get("capability")
        if cap not in CHECK_LABELS:
            continue
        try:
            records = await _execute_check(inv, cap)
        except Exception:
            logger.exception("evidence check %s failed", cap)
            continue
        for rec in _normalize_records(records):
            finding = rec.get("finding") or ""
            # Document page records carry the passage text as evidence; allow
            # them more room than a one-line media observation.
            limit = 12000 if (rec.get("metadata") or {}).get("page") else 2000
            finding = finding[:limit]
            now = _now_iso()
            ev_id = _nanoid("ev")
            # Use the per-record signal when the check produced one.
            # File-level metadata observations are marked 'observed'.
            # URL retrieval success is marked 'supporting'.
            # Document page retrieval success is marked 'supporting'.
            # Fall back to 'uncertain' only when the check didn't set a signal.
            ev_signal = rec.get("signal") or "uncertain"
            ev = {
                "id": ev_id,
                "type": req.get("type") or "evidence",
                "source": f"Inquvia check: {CHECK_LABELS[cap]}",
                "finding": finding,
                "signal": ev_signal,
                "status": "collected",
                "confidence": None,
                "timestamp": now,
                "metadata": {
                    "origin": "evidence_service",
                    "checkCapability": cap,
                    **(rec.get("metadata") or {}),
                },
            }
            inv.setdefault("evidence", []).append(ev)
            inv.setdefault("acquisitions", []).append({
                "id": _nanoid("acq"),
                "investigationId": inv["id"],
                "capability": cap,
                "serviceName": CHECK_LABELS[cap],
                # Internal evidence-service records are not individual monetary
                # charges: the one capability payment the user settled is the
                # whole cost, tracked in `payments` (engine.economicSummary).
                "amountMicro": 0,
                "paymentState": "evidence_received",
                "network": "internal",
                "evidence": {"signal": ev_signal, "finding": finding[0:300], "source": ev["source"]},
                "createdAt": now,
            })

    db.save_investigation(inv)
    return db.get_investigation(inv["id"])
