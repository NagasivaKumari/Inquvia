"""Core-owned evidence endpoints.
These endpoints process user-supplied material locally through Inquvia's
storage, deterministic helpers, URL inspector, and configured AI tools.
They never discover or pay another evidence service.
"""

import csv
import io
import json
import re
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from .. import config, db
from ..libraries import ai, source_input, storage
from ..libraries import image_c2pa, image_forensics
from ..libraries.analyze import heuristic_analysis
from ..libraries.evidence_validation import (
    ErrorCode,
    ErrorResponse,
    EvidenceValidator,
)
from ..libraries.contract_registry import (
    image_contract,
    video_contract,
    audio_contract,
    document_contract,
    authenticity_contract,
    url_contract,
    structured_contract,
    assess_contract,
    contradictions_contract,
    duplicates_contract,
    timeline_contract,
    gaps_contract,
    get_all_evidence_contracts,
)

router = APIRouter()


def _id(prefix: str = "") -> str:
    """Generate a unique ID."""
    suffix = secrets.token_hex(8)
    return f"{prefix}_{suffix}" if prefix else suffix


def _now() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _envelope(
    kind: str,
    finding: str,
    claim: str = "",
    facts: list | None = None,
    observations: list | None = None,
    sources: list | None = None,
    metadata: dict | None = None,
) -> dict:
    result: dict = {
        "id": _id(),
        "source_type": kind,
        "status": "extracted",
        "finding": finding,
        "content": finding,
        "metadata": metadata or {},
        "extraction_quality": {
            "method": "direct",
            "success": True,
            "features_detected": [],
            "page_range": None,
        },
        "confidence_metrics": {"overall": 0.0},
    }
    if claim:
        result["claim"] = claim
    if facts:
        result["facts"] = facts
    if observations:
        result["observations"] = observations
    if sources:
        result["sources"] = sources
    return result


def _resolve_evidence_user_id(request: Request | None) -> str | None:
    if not request:
        return None
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return str(user_id)
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return str(user["id"])
    try:
        from ..auth import verify_jwt, get_current_user_from_cookie, SESSION_COOKIE
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            uid = verify_jwt(auth_header.split(" ")[1])
            if uid:
                return str(uid)
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie:
            u = get_current_user_from_cookie(cookie)
            if u and u.get("id"):
                return str(u["id"])
    except Exception:
        pass
    return None


def _persist(request: Request, operation: str, inputs: dict, result: dict) -> dict:
    """Save the request/result pair before returning a direct evidence response."""
    request_id = _id("inv")
    user_id = _resolve_evidence_user_id(request)

    req_doc = {
        "requestId": request_id,
        "operation": operation,
        "userId": user_id,
        "inputs": inputs,
        "result": result,
        "createdAt": _now(),
    }
    db.save_evidence_request(req_doc)

    try:
        inv_doc = db._evidence_request_to_investigation(req_doc)
        if inv_doc:
            db.save_investigation(inv_doc)
    except Exception as e:
        import logging
        logging.warning(f"Failed to auto-save investigation for {operation}: {e}")

    if request:
        request.state.investigation_id = request_id
        request.state.capability = operation

    result["id"] = request_id
    result["requestId"] = request_id
    result["investigationId"] = request_id
    result["persistence"] = {
        "store": "mongodb",
        "collection": "evidence_requests",
        "status": "saved",
    }
    return result


async def _ai_finding(kind: str, claim: str, parts: list[dict]) -> dict:
    from ..libraries.training import few_shot_block

    prompt = (
        f"You are Inquvia's {kind} evidence analyst. Analyze only the supplied input. "
        "Return JSON with finding (string), observations (array of strings), facts (array of strings), "
        "confidence (0 to 1), and limitations (array of strings). Do not claim certainty."
    ) + few_shot_block(kind)
    raw = ai.parse_ai_json(
        await ai.call_ai_with_parts(
            prompt, [{"text": f"CLAIM: {claim}"}, *parts], task=kind
        )
    )
    return raw if isinstance(raw, dict) else {}


@router.get("/api/evidence/contracts")
async def get_contracts():
    """Return the authoritative contract metadata for all evidence endpoints."""
    return [c.model_dump() for c in get_all_evidence_contracts()]


# ── File and URL Endpoints ──
_FILE_CONTRACTS = {
    "image": image_contract,
    "video": video_contract,
    "audio": audio_contract,
    "document": document_contract,
}


def _raise_validation(
    code: str, message: str, field: str, status_code: int = 400
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ErrorResponse(error=code, message=message, field=field).model_dump(),
    )


async def _request_data(request: Request) -> tuple[dict, list[dict]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "INVALID_BODY_SCHEMA", "message": str(exc)},
            ) from exc
        files = []
        uploads = form.getlist("files") or form.getlist("file")
        for upload in uploads:
            data = await upload.read(config.MAX_UPLOAD_SIZE + 1)
            if len(data) > config.MAX_UPLOAD_SIZE:
                _raise_validation(
                    "FILE_TOO_LARGE",
                    f"The file is too large. Maximum file size is {config.MAX_UPLOAD_SIZE_MB}MB.",
                    "file",
                    413,
                )
            files.append(
                {
                    "data": data,
                    "name": upload.filename or "upload.bin",
                    "mime": source_input.normalize_upload_mime(
                        data, upload.content_type, upload.filename or "upload.bin"
                    ),
                }
            )
        body = {
            key: form.get(key)
            for key in (
                "claim",
                "url",
                "payload",
                "question",
                "max_frames",
                "evidence",
                "serviceName",
            )
            if key in form
        }
        if isinstance(body.get("evidence"), str) and body["evidence"].strip():
            try:
                body["evidence"] = json.loads(body["evidence"])
            except json.JSONDecodeError as exc:
                _raise_validation(
                    "INVALID_BODY_SCHEMA",
                    "The evidence field must be valid JSON.",
                    "evidence",
                )
        return body, files
    try:
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > config.MAX_UPLOAD_SIZE:
                _raise_validation(
                    "FILE_TOO_LARGE",
                    f"The request is too large. Maximum size is {config.MAX_UPLOAD_SIZE_MB}MB.",
                    "body",
                    413,
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
        body = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        _raise_validation(
            "INVALID_JSON", "The request body must be valid JSON.", "body"
        )
    if not isinstance(body, dict):
        _raise_validation(
            "INVALID_BODY_SCHEMA", "The request body must be a JSON object.", "body"
        )
    return body, []


def _contract_for_kind(kind: str):
    if kind in _FILE_CONTRACTS:
        return _FILE_CONTRACTS[kind]()
    if kind == "authenticity":
        return authenticity_contract()
    if kind == "structured":
        return structured_contract()
    return url_contract()


def _remote_mimes(kind: str, contract) -> set[str]:
    if kind == "url":
        return set(source_input.ANALYSIS_MIMES)
    if kind == "document":
        return set(contract.accepted_mimetypes) | set(source_input.HTML_MIMES)
    return set(contract.accepted_mimetypes)


async def _resolve_source(
    request: Request, kind: str, file: dict | None, url: str
) -> dict:
    if file and url:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Provide either a file or a URL, not both.", "url"
        )
    if url:
        sanitized = storage.sanitize_url(url)
        if not sanitized:
            _raise_validation(
                "INVALID_URL", "Please enter a valid HTTP or HTTPS URL.", "url"
            )
        contract = _contract_for_kind(kind)
        try:
            remote = await source_input.fetch_url(
                sanitized, _remote_mimes(kind, contract)
            )
            inspection = source_input.inspect_source(remote)
            stored = source_input.store_remote_input(
                remote,
                _id("case"),
                input_type=kind,
                inspection=inspection,
            )
        except source_input.SourceInputError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.content
            ) from exc
        return {
            "data": remote.data,
            "mime": remote.mime_type,
            "filename": remote.filename,
            "size": len(remote.data),
            "filePath": stored["filePath"],
            "sourceUrl": remote.requested_url,
            "finalUrl": remote.final_url,
            "inspection": inspection,
            "storedInput": stored,
        }
    if not file:
        _raise_validation(
            "MISSING_REQUIRED_FIELD", "Please provide a file or URL.", "file"
        )
    contract = _contract_for_kind(kind)
    data = file["data"]
    mime = file["mime"]
    ok, error_resp = EvidenceValidator.validate_file_upload(
        mime,
        len(data),
        contract.accepted_mimetypes,
        contract.max_file_size_mb,
    )
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    try:
        source_input.validate_upload_mime(data, mime, "file")
    except source_input.SourceInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.content) from exc
    stored = storage.store_file(data, file["name"], mime, _id("case"))
    return {
        "data": data,
        "mime": mime,
        "filename": file["name"],
        "size": len(data),
        "filePath": stored["filePath"],
        "sourceUrl": None,
        "finalUrl": None,
        "inspection": None,
        "storedInput": stored,
    }


async def _file_evidence(
    request: Request,
    kind: str,
    file: dict | None = None,
    claim: str = "",
    max_frames: int | None = None,
    url: str = "",
) -> dict:
    source = await _resolve_source(request, kind, file, url)
    import base64

    raw = await _ai_finding(
        kind,
        claim,
        [
            {
                "file": {
                    "mimeType": source["mime"],
                    "base64": base64.b64encode(source["data"]).decode("ascii"),
                }
            },
        ],
    )
    metadata = {
        "filename": source["filename"],
        "mimeType": source["mime"],
        "size": source["size"],
        "filePath": source["filePath"],
        "ai": raw,
    }
    if source.get("sourceUrl"):
        metadata.update(
            {"sourceUrl": source["sourceUrl"], "finalUrl": source["finalUrl"]}
        )
    result = _envelope(
        kind,
        raw.get("finding") or f"{kind.title()} processed: {source['filename']}.",
        claim=claim,
        facts=raw.get("facts"),
        observations=raw.get("observations"),
        metadata=metadata,
    )
    if max_frames is not None:
        result["metadata"]["maxFrames"] = max(2, min(40, max_frames))
    inputs = {
        "claim": claim,
        "filename": source["filename"],
        "mimeType": source["mime"],
    }
    if source.get("sourceUrl"):
        inputs["url"] = source["sourceUrl"]
    return _persist(request, kind, inputs, result) if request else result


@router.post("/api/evidence/image")
async def image_evidence(request: Request):
    """Process and analyze an image file or image URL for evidence extraction."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one image source may be submitted.", "file"
        )
    return await _file_evidence(
        request,
        "image",
        files[0] if files else None,
        payload.get("claim") or "",
        url=payload.get("url") or "",
    )


@router.post("/api/evidence/video")
async def video_evidence(request: Request):
    """Process and analyze a video file or video URL for evidence extraction."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one video source may be submitted.", "file"
        )
    raw_frames = payload.get("max_frames", 8)
    try:
        max_frames = int(raw_frames)
    except (TypeError, ValueError):
        _raise_validation(
            "INVALID_FIELD_VALUE", "max_frames must be a number.", "max_frames"
        )
    ok, error_resp = EvidenceValidator.validate_number_field(
        max_frames, "max_frames", 2, 40, "maximum frames"
    )
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    return await _file_evidence(
        request,
        "video",
        files[0] if files else None,
        payload.get("claim") or "",
        max_frames,
        payload.get("url") or "",
    )


@router.post("/api/evidence/audio")
async def audio_evidence(request: Request):
    """Process and analyze an audio file or audio URL for evidence extraction."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one audio source may be submitted.", "file"
        )
    return await _file_evidence(
        request,
        "audio",
        files[0] if files else None,
        payload.get("claim") or "",
        url=payload.get("url") or "",
    )


@router.post("/api/evidence/document")
async def document_evidence(request: Request):
    """Process and analyze a document file or document URL for evidence extraction."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one document source may be submitted.", "file"
        )
    return await _file_evidence(
        request,
        "document",
        files[0] if files else None,
        payload.get("claim") or "",
        url=payload.get("url") or "",
    )


@router.post("/api/evidence/authenticity")
async def authenticity_evidence(request: Request):
    """Perform forensic analysis to check media authenticity signals."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one media source may be submitted.", "file"
        )
    source = await _resolve_source(
        request,
        "authenticity",
        files[0] if files else None,
        payload.get("url") or "",
    )
    data, mime = source["data"], source["mime"]
    import base64

    raw = await _ai_finding(
        "authenticity",
        "",
        [
            {
                "file": {
                    "mimeType": mime,
                    "base64": base64.b64encode(data).decode("ascii"),
                }
            },
        ],
    )
    c2pa = image_c2pa.analyze(data)
    forensics = (
        image_forensics.analyze_image(data, mime) if mime.startswith("image/") else {}
    )
    sig_bits = [image_c2pa.describe(c2pa)]
    if forensics:
        tamper = forensics.get("tamperSignals") or {}
        fbits = [
            f"perceptualHash={forensics.get('perceptualHash')}",
            f"format={forensics.get('format')}",
            f"estimatedQuality={forensics.get('estimatedQuality')}",
            f"reencodeSignals={forensics.get('jpegQuantizationStandard')}",
        ]
        if tamper.get("warnings"):
            fbits.append(f"tamperSignals warnings={tamper['warnings']}")
        for key in (
            "editorIdentified",
            "dateMismatch",
            "exifAbsent",
            "hasGps",
            "cameraMake",
            "cameraModel",
        ):
            if tamper.get(key):
                fbits.append(f"{key}={tamper[key]}")
        sig_bits.append(
            "Image forensics: "
            + "; ".join(f for f in fbits if f and not str(f).endswith("=None"))
        )
    verdict, verdict_reason = _authenticity_verdict(c2pa, forensics, raw)
    sig_bits.append(f"OPINION VERDICT: {verdict} — {verdict_reason}")
    sig_text = "\n".join(sig_bits)
    metadata = {
        "filename": source["filename"],
        "mimeType": mime,
        "size": source["size"],
        "filePath": source["filePath"],
        "ai": raw,
        "c2pa": c2pa,
        "forensics": forensics,
        "forensicSignals": sig_text,
        "verdict": verdict,
        "verdictReason": verdict_reason,
    }
    if source.get("sourceUrl"):
        metadata.update(
            {"sourceUrl": source["sourceUrl"], "finalUrl": source["finalUrl"]}
        )
    result = _envelope(
        "authenticity",
        raw.get("finding") or f"Authenticity analysis: {source['filename']}.",
        metadata=metadata,
    )
    result["content"] = sig_text
    result.setdefault("metadata", {})["forensicMode"] = "signals-plus-ai"
    inputs = {"filename": source["filename"], "mimeType": mime}
    if source.get("sourceUrl"):
        inputs["url"] = source["sourceUrl"]
    return _persist(request, "authenticity", inputs, result) if request else result


def _authenticity_verdict(c2pa: dict, forensics: dict, ai_raw: dict) -> tuple[str, str]:
    """Derived opinion combining crypto provenance, edit signals, and AI read.
    Opinion, not proof — the caller decides. Precedence: crypto > edit signals > AI.
    """
    tamper = forensics.get("tamperSignals") or {}
    ela = forensics.get("ela") or {}
    edit_signals = [
        name
        for name, val in (
            ("editorIdentified", tamper.get("editorIdentified")),
            ("dateMismatch", tamper.get("dateMismatch")),
        )
        if val
    ]
    if ela and ela.get("elevatedErrorBlocks"):
        edit_signals.append(
            f"reencode (ELA elevated blocks={ela['elevatedErrorBlocks']})"
        )
    trusted = bool(c2pa.get("signerTrusted"))
    valid = c2pa.get("validationState") in ("Valid",)
    markers = bool(c2pa.get("credentialsPresent"))
    if trusted and not edit_signals:
        verdict, reason = (
            "likely_authentic",
            "C2PA signature verified against trust anchors and no editing signals found.",
        )
    elif trusted and edit_signals:
        verdict, reason = (
            "authentic_with_edits",
            "C2PA signature trusted but editing signals present (edits may be benign/recorded).",
        )
    elif valid:
        verdict, reason = (
            "provenance_attested",
            "C2PA signature cryptographically valid but signer not in the official trust list.",
        )
    elif markers:
        verdict, reason = (
            "provenance_claimed",
            "C2PA/Content Credentials markers present but not cryptographically verified.",
        )
    elif edit_signals:
        verdict, reason = (
            "editing_indicators",
            f"Editing signals detected without any C2PA provenance: {', '.join(edit_signals)}.",
        )
    else:
        verdict, reason = (
            "undetermined",
            "No C2PA provenance and no editing signals — insufficient evidence either way.",
        )
    conf = ai_raw.get("confidence")
    if isinstance(conf, (int, float)):
        reason += f" (AI read confidence {conf:.2f})"
    return verdict, reason


# ── URL Endpoint (with clear error messages) ──
@router.post("/api/evidence/url")
async def url_evidence(request: Request):
    """Inspect and analyze a public URL for evidence extraction."""
    payload, files = await _request_data(request)
    if files:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "The URL endpoint accepts a URL only.", "file"
        )
    url = (payload.get("url") or "").strip()
    ok, error_resp = EvidenceValidator.validate_required_field(url, "url", "a URL")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    ok, error_resp = EvidenceValidator.validate_url(url)
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    try:
        remote = await source_input.fetch_url(url, source_input.ANALYSIS_MIMES)
        inspection = source_input.inspect_source(remote)
        stored = source_input.store_remote_input(
            remote, _id("case"), input_type="url", inspection=inspection
        )
    except source_input.SourceInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.content) from exc
    claim = (payload.get("claim") or "").strip()
    raw = await _ai_finding(
        "web source", claim, [{"text": json.dumps(inspection or {})}]
    )
    result = _envelope(
        "url",
        raw.get("finding") or "Source inspected.",
        claim=claim,
        observations=raw.get("observations"),
        facts=raw.get("facts"),
        sources=[url],
        metadata={
            "inspection": inspection,
            "ai": raw,
            "filename": remote.filename,
            "mimeType": remote.mime_type,
            "filePath": stored["filePath"],
            "sourceUrl": url,
            "finalUrl": remote.final_url,
        },
    )
    return _persist(request, "url", {"url": url, "claim": claim}, result)


# ── Structured Data Endpoint (with clear error messages) ──
@router.post("/api/evidence/structured")
async def structured_evidence(request: Request):
    """Analyze a JSON or CSV data source for evidence extraction."""
    payload, files = await _request_data(request)
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA",
            "Only one structured data source may be submitted.",
            "file",
        )
    raw_payload = payload.get("payload")
    if isinstance(raw_payload, (dict, list)):
        content = json.dumps(raw_payload)
    else:
        content = str(raw_payload or "")
    provided = sum(
        bool(value)
        for value in (content, files[0] if files else None, payload.get("url"))
    )
    if provided > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Provide one of payload, file, or URL.", "payload"
        )
    if not provided:
        _raise_validation(
            "MISSING_REQUIRED_FIELD",
            "Please provide a JSON/CSV file, URL, or pasted content.",
            "payload",
        )
    source = None
    if files or payload.get("url"):
        source = await _resolve_source(
            request,
            "structured",
            files[0] if files else None,
            payload.get("url") or "",
        )
        content = source["data"].decode("utf-8", errors="replace")
    if not content.strip():
        _raise_validation("INVALID_JSON", "The structured data is empty.", "payload")
    try:
        parsed = json.loads(content)
        summary = {
            "kind": "json",
            "keys": list(parsed)[:50] if isinstance(parsed, dict) else [],
            "records": len(parsed) if isinstance(parsed, list) else 1,
        }
    except json.JSONDecodeError:
        try:
            rows = list(csv.reader(io.StringIO(content)))
            if not rows:
                raise ValueError("empty")
            summary = {"kind": "csv", "columns": rows[0], "rows": max(0, len(rows) - 1)}
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error=ErrorCode.INVALID_CSV,
                    message="The content is neither valid JSON nor valid CSV. Please check your format and try again.",
                    field="payload",
                ).model_dump(),
            ) from exc
    inputs = {"claim": payload.get("claim") or "", "summary": summary}
    if source:
        inputs.update({"filename": source["filename"], "mimeType": source["mime"]})
        if source.get("sourceUrl"):
            inputs["url"] = source["sourceUrl"]
    return _persist(
        request,
        "structured",
        inputs,
        _envelope(
            "structured",
            f"Structured data processed: {summary}.",
            claim=payload.get("claim") or "",
            metadata=summary,
        ),
    )


# ── Evidence Analysis Endpoints (JSON-based with clear error messages) ──
async def _analysis_data(
    request: Request, minimum: int
) -> tuple[dict, list[dict], dict]:
    payload, files = await _request_data(request)
    evidence = payload.get("evidence")
    if isinstance(evidence, str) and evidence.strip():
        try:
            evidence = json.loads(evidence)
        except json.JSONDecodeError:
            _raise_validation(
                "INVALID_BODY_SCHEMA",
                "The evidence field must be valid JSON.",
                "evidence",
            )
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        _raise_validation(
            "INVALID_BODY_SCHEMA", "The evidence must be a list of items.", "evidence"
        )
    if len(files) > 1:
        _raise_validation(
            "INVALID_BODY_SCHEMA", "Only one PDF may be submitted.", "file"
        )
    source_items = []
    source_inputs = []
    if files:
        file = files[0]
        ok, error_resp = EvidenceValidator.validate_file_upload(
            file["mime"],
            len(file["data"]),
            ["application/pdf"],
            config.MAX_UPLOAD_SIZE_MB,
        )
        if not ok:
            raise HTTPException(status_code=415, detail=error_resp.model_dump())
        try:
            source_input.validate_upload_mime(file["data"], file["mime"], "file")
        except source_input.SourceInputError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.content
            ) from exc
        stored = storage.store_file(
            file["data"], file["name"], file["mime"], _id("case")
        )
        source_items.extend(
            source_input.evidence_items(file["data"], file["mime"], file["name"])
        )
        source_inputs.append(
            {
                "filename": file["name"],
                "mimeType": file["mime"],
                "filePath": stored["filePath"],
            }
        )
    if payload.get("url"):
        try:
            remote = await source_input.fetch_url(
                payload["url"], source_input.ANALYSIS_MIMES
            )
            inspection = source_input.inspect_source(remote)
            stored = source_input.store_remote_input(
                remote, _id("case"), input_type="url", inspection=inspection
            )
        except source_input.SourceInputError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.content
            ) from exc
        source_items.extend(
            source_input.evidence_items(
                remote.data,
                remote.mime_type,
                remote.filename,
                remote.requested_url,
                inspection,
            )
        )
        source_inputs.append(
            {
                "url": remote.requested_url,
                "filename": remote.filename,
                "mimeType": remote.mime_type,
                "filePath": stored["filePath"],
                "finalUrl": remote.final_url,
            }
        )
    all_evidence = evidence + source_items
    if len(all_evidence) < minimum:
        _raise_validation(
            "MISSING_REQUIRED_FIELD",
            f"You need at least {minimum} evidence item(s) for this endpoint.",
            "evidence",
        )
    persistence = dict(payload)
    if source_inputs:
        persistence["sourceInputs"] = source_inputs
    return payload, all_evidence, persistence


@router.post("/api/evidence/assess")
async def assess_evidence(request: Request):
    """Assess a claim against supplied evidence or an extracted source."""
    payload, evidence_payload, persistence = await _analysis_data(request, 1)
    if not all(
        isinstance(item, dict) and item.get("status") == "extracted"
        for item in evidence_payload
    ):
        _raise_validation(
            "INVALID_BODY_SCHEMA",
            "All evidence items must have status 'extracted'.",
            "evidence",
        )
    evidence = _refs(evidence_payload)
    result = heuristic_analysis(
        {"question": payload.get("claim") or "", "evidenceRequirements": []},
        evidence,
    )
    return _persist(
        request,
        "assess",
        persistence,
        {
            "type": "assessment",
            "claim": payload.get("claim") or "",
            "verdict": result["conclusion"],
            "confidence": result["confidence"] / 100,
            "findings": result["findings"],
            "limitations": result["limitations"],
        },
    )


@router.post("/api/evidence/contradictions")
async def contradictions_evidence(request: Request):
    """Find contradictions in supplied evidence items."""
    payload, evidence_payload, persistence = await _analysis_data(request, 2)
    evidence = _refs(evidence_payload)
    pairs = []
    for left_index, left in enumerate(evidence):
        left_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", left["finding"])
        for right in evidence[left_index + 1 :]:
            right_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", right["finding"])
            if left_numbers and right_numbers and left_numbers != right_numbers:
                pairs.append(
                    {
                        "left": left["id"],
                        "right": right["id"],
                        "reason": "Different numeric observations.",
                    }
                )
    return _persist(
        request,
        "contradictions",
        persistence,
        {"type": "contradictions", "contradictions": pairs, "count": len(pairs)},
    )


@router.post("/api/evidence/duplicates")
async def duplicates_evidence(request: Request):
    """Find duplicate and dependent evidence items."""
    payload, evidence_payload, persistence = await _analysis_data(request, 1)
    evidence = _refs(evidence_payload)
    groups = {}
    for item in evidence:
        groups.setdefault(
            re.sub(r"\W+", " ", item["finding"].lower()).strip(), []
        ).append(item["id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    return _persist(
        request,
        "duplicates",
        persistence,
        {
            "type": "duplicates",
            "duplicates": duplicates,
            "independent_count": len(evidence)
            - sum(len(ids) - 1 for ids in duplicates),
        },
    )


@router.post("/api/evidence/timeline")
async def timeline_evidence(request: Request):
    """Reconstruct a timeline from supplied evidence items."""
    payload, evidence_payload, persistence = await _analysis_data(request, 1)
    events = []
    for item in evidence_payload:
        dates = re.findall(
            r"\b(?:19|20)\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?\b", json.dumps(item)
        )
        events.extend(
            {
                "date": date,
                "evidence_id": item.get("evidence_id") or item.get("id"),
                "text": item.get("text") or item.get("finding", ""),
            }
            for date in dates
        )
    return _persist(
        request, "timeline", persistence, {"type": "timeline", "events": events}
    )


@router.post("/api/evidence/gaps")
async def gaps_evidence(request: Request):
    """Identify missing evidence and unresolved questions."""
    payload, evidence_payload, persistence = await _analysis_data(request, 0)
    return _persist(
        request,
        "gaps",
        persistence,
        {
            "type": "gaps",
            "status": (
                "supported" if len(evidence_payload) >= 2 else "insufficient_evidence"
            ),
            "missing": [] if evidence_payload else ["independent evidence"],
            "unresolved_questions": (
                []
                if evidence_payload
                else [payload.get("claim") or "Provide evidence for this claim."]
            ),
        },
    )


# ── Helper functions ──
def _refs(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (
            item.get("text")
            or item.get("finding")
            or item.get("claim")
            or json.dumps(item)
        )
        result.append(
            {
                "id": item.get("evidence_id") or item.get("id") or _id(),
                "status": "collected",
                "type": item.get("type", "text"),
                "finding": text,
                "source": (item.get("sources") or ["submitted evidence"])[0],
                "confidence": item.get("confidence", 0),
                "signal": item.get("signal", "uncertain"),
                "metadata": item.get("metadata") or {},
            }
        )
    return result
