"""Executable evidence checks (the "services" advertised on the evidence page).

Each planned evidence requirement whose capability maps to a runnable
deterministic check is executed server-side against the user's submission and
recorded as acquired evidence (origin "evidence_service"). Checks that would
require an external provider we don't have (reverse-image indexes, WHOIS,
search engines, transcription) are skipped and simply are not counted.

ponytail: no model calls here — these are reproducible observations; the
analyzer later reasons over them and gives the verdict.
"""
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
from ..libraries.video_processor import (
    VideoProcessor,
    artifacts_dir,
    frame_payload_bytes,
    materialize_source,
    prepare_video,
)
from ..libraries.analyze import read_stored_text, run_ai_ocr

logger = logging.getLogger(__name__)

CHECK_LABELS = {
    "image_provenance": "Image provenance & metadata analysis",
    "image_metadata": "Image metadata / EXIF inspection",
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
        
        records.append({
            "finding": desc or f"{kind.capitalize()} check ({label}): no observable file-level metadata extracted.",
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
    return {
        "finding": finding,
        "metadata": meta,
    }


_FRAME_OBSERVE_PROMPT = (
    "You are a forensic frame-observation step for a video investigation. For each attached frame, captioned "
    "'FRAME at t=X.XXs', describe ONLY what is directly visible in that single frame: objects, people, setting, "
    "colors, readable text, lighting, motion blur. The timestamp caption is the capture time to echo back; "
    "nothing else. Do not infer events before or after the frame, do not guess the video's story, and do not "
    "reason from the user's investigation question. If a frame is too dark, blurry, or otherwise unreadable to "
    "identify content, set 'unclear': true and describe only what can reliably be seen (possibly nothing); "
    "never invent content that is not visible. "
    'Return ONLY JSON: {"frames": [{"timestamp": <number>, "visibleContent": <string>, "unclear": <boolean>}]}.'
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


async def _observe_frames(inp: dict, label: str, extract: dict) -> dict:
    """Direct visual observation of each extracted frame, keyed by timestamp.

    The multimodal AI is asked what is directly visible in each frame
    (question-independent, one batch per video, one result per timestamp).
    Observations are cached on the extraction record so the evidence checks,
    the analyzer and repeated runs reuse the same result. Uses the multimodal
    path (Gemini → Experiential); without a working multimodal provider no
    observation is invented and frame records degrade to honest timestamp
    metadata (see _frame_record).
    """
    frames = extract.get("frames") or []
    if not frames:
        return {}
    if extract.get("frameObservations"):
        return frame_observations_by_time(extract)
    # No multimodal provider available → honest empty result, no fabrication
    if not config.GEMINI_API_KEY and not config.EXPLABS_API_KEY and not config.OPENROUTER_API_KEY:
        return {}
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
        text = await ai_lib.call_ai_with_parts(_FRAME_OBSERVE_PROMPT, parts, text_fallback=False)
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
            observations = await _observe_frames(inp, _labelled(inp), extract)
            frames = extract.get("frames") or []
            for frame in frames:
                records.append(_frame_record(
                    inp, _labelled(inp), frame, len(frames),
                    observations.get(round(frame["timestamp"], 2)),
                ))
            rec = await _transcription_record(inp, _labelled(inp), extract)
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
        extracted = await document_extract.extract_document_pages_with_ocr(
            stored, inp.get("mimeType"), run_ai_ocr
        )
        if not extracted or not extracted.get("pages"):
            records.append({
                "finding": f"Document check ({label}): no readable text could be extracted — evidence unavailable.",
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
            else:
                finding = (
                    f"Document check ({label}), page {page['page']} [{source_label}]: "
                    "no readable text was recovered (scanned page, OCR returned nothing)."
                )
            records.append({
                "finding": finding,
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
                "metadata": {"url": url, "evidenceAvailable": False},
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

        # A successful retrieval (2xx + content present) is supporting evidence
        # for any question about the page. Blocked/failed retrievals stay uncertain.
        if is_online and has_content and not blocked:
            signal = "supporting"
        elif blocked or not is_online:
            signal = "uncertain"
        else:
            signal = "uncertain"

        records.append({
            "finding": ", ".join(bits),
            "signal": signal,
            "metadata": {
                "url": url,
                "statusCode": status,
                "isOnline": is_online,
                "sslValid": inspection.get("sslValid"),
                "title": inspection.get("title"),
                "contentLength": inspection.get("totalTextLength", 0),
                "hasContent": has_content,
                "blocked": blocked,
                "evidenceAvailable": is_online and not blocked,
                # Full extracted text so the analyzer can quote exact values.
                "fullText": (inspection.get("fullText") or "")[:60000],
                "bodySnippet": inspection.get("bodySnippet") or "",
                "headings": inspection.get("headings") or [],
                "paragraphs": (inspection.get("paragraphs") or [])[:100],
                "tables": inspection.get("tables") or [],
                "metaDescription": inspection.get("metaDescription") or "",
            },
        })
    return records


async def _execute_check(inv: dict, cap: str):
    """Runnable checks return a mix of plain finding strings (text checks) and
    structured records {finding, metadata} (media checks)."""
    if cap in ("video_analysis", "frame_evidence", "audio_transcription"):
        return await _video_findings(inv, cap)
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
            # Use the per-record signal when the check produced one (e.g. URL
            # retrieval success → 'supporting'); fall back to 'uncertain'.
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
