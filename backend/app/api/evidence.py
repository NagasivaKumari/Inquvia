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
from typing import Any, Dict, Literal, Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from .. import db
from ..libraries import ai, storage, web_inspector
from ..libraries.analyze import heuristic_analysis
from ..libraries.evidence_types import EvidenceResult
from ..libraries.evidence_validation import (
    ErrorCode,
    ErrorResponse,
    EvidenceValidationError,
    EvidenceValidator,
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
)

router = APIRouter()


def _id(prefix: str = "") -> str:
    """Generate a unique ID."""
    suffix = secrets.token_hex(8)
    return f"{prefix}_{suffix}" if prefix else suffix


def _now() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _envelope(kind: str, status: Literal["pending", "retrieved", "extracted", "failed"],
              finding: str, content: str = "", metadata: dict = None) -> EvidenceResult:
    return EvidenceResult(
        id=_id(),
        source_type=kind,
        status=status,
        content=content,
        extraction_quality={"method": "direct", "success": status == "extracted", "features_detected": [], "page_range": None} if status == "extracted" else None,
        confidence_metrics={"overall": 0.0}
    )


def _persist(request: Request, operation: str, inputs: dict, result: dict) -> dict:
    """Save the request/result pair before returning a direct evidence response."""
    request_id = _id("req")
    db.save_evidence_request({
        "requestId": request_id,
        "operation": operation,
        "userId": getattr(request.state, "user_id", None),
        "inputs": inputs,
        "result": result,
        "createdAt": _now(),
    })
    result["requestId"] = request_id
    result["persistence"] = {"store": "mongodb", "collection": "evidence_requests", "status": "saved"}
    return result


async def _ai_finding(kind: str, claim: str, parts: list[dict]) -> dict:
    prompt = (
        f"You are Inquvia's {kind} evidence analyst. Analyze only the supplied input. "
        "Return JSON with finding (string), observations (array of strings), facts (array of strings), "
        "confidence (0 to 1), and limitations (array of strings). Do not claim certainty."
    )
    raw = ai.parse_ai_json(await ai.call_ai_with_parts(prompt, [{"text": f"CLAIM: {claim}"}, *parts]))
    return raw if isinstance(raw, dict) else {}


# ── File Upload Endpoints (with clear error messages) ──

@router.post("/api/evidence/image")
async def image_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    """Process and analyze an image file for evidence extraction."""
    # Validate file upload against contract
    allowed_mimetypes = image_contract().accepted_mimetypes
    max_size_mb = image_contract().max_file_size_mb
    
    data = await file.read()
    ok, error_resp = EvidenceValidator.validate_file_upload(
        file.content_type, len(data), allowed_mimetypes, max_size_mb
    )
    
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding("image", claim, [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        "image", raw.get("finding") or f"Image processed: {file.filename or 'upload'}.",
        claim=claim, facts=raw.get("facts"), observations=raw.get("observations"),
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    return _persist(request, "image", {"claim": claim, "filename": file.filename, "mimeType": file.content_type}, result) if request else result


@router.post("/api/evidence/video")
async def video_evidence(request: Request, file: UploadFile = File(...), claim: str = Form(""), max_frames: int = Form(8)):
    """Process and analyze a video file for evidence extraction."""
    # Validate max_frames
    ok, error_resp = EvidenceValidator.validate_number_field(max_frames, "max_frames", 2, 40, "maximum frames")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    # Validate file upload against contract
    allowed_mimetypes = video_contract().accepted_mimetypes
    max_size_mb = video_contract().max_file_size_mb
    
    data = await file.read()
    ok, error_resp = EvidenceValidator.validate_file_upload(
        file.content_type, len(data), allowed_mimetypes, max_size_mb
    )
    
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding("video", claim, [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        "video", raw.get("finding") or f"Video processed: {file.filename or 'upload'}.",
        claim=claim, facts=raw.get("facts"), observations=raw.get("observations"),
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    if "metadata" in result:
        result["metadata"]["maxFrames"] = max(2, min(40, max_frames))
    return _persist(request, "video", {"claim": claim, "filename": file.filename, "mimeType": file.content_type}, result) if request else result


@router.post("/api/evidence/audio")
async def audio_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    """Process and analyze an audio file for evidence extraction."""
    # Validate file upload against contract
    allowed_mimetypes = audio_contract().accepted_mimetypes
    max_size_mb = audio_contract().max_file_size_mb
    
    data = await file.read()
    ok, error_resp = EvidenceValidator.validate_file_upload(
        file.content_type, len(data), allowed_mimetypes, max_size_mb
    )
    
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding("audio", claim, [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        "audio", raw.get("finding") or f"Audio processed: {file.filename or 'upload'}.",
        claim=claim, facts=raw.get("facts"), observations=raw.get("observations"),
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    return _persist(request, "audio", {"claim": claim, "filename": file.filename, "mimeType": file.content_type}, result) if request else result


@router.post("/api/evidence/document")
async def document_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    """Process and analyze a document file for evidence extraction."""
    # Validate file upload against contract
    allowed_mimetypes = document_contract().accepted_mimetypes
    max_size_mb = document_contract().max_file_size_mb
    
    data = await file.read()
    ok, error_resp = EvidenceValidator.validate_file_upload(
        file.content_type, len(data), allowed_mimetypes, max_size_mb
    )
    
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding("document", claim, [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        "document", raw.get("finding") or f"Document processed: {file.filename or 'upload'}.",
        claim=claim, facts=raw.get("facts"), observations=raw.get("observations"),
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    return _persist(request, "document", {"claim": claim, "filename": file.filename, "mimeType": file.content_type}, result) if request else result


@router.post("/api/evidence/authenticity")
async def authenticity_evidence(request: Request, file: UploadFile = File(...)):
    """Perform forensic analysis to check media authenticity signals."""
    # Validate file upload against contract (accepts image, video, audio)
    allowed_mimetypes = authenticity_contract().accepted_mimetypes
    max_size_mb = authenticity_contract().max_file_size_mb
    
    data = await file.read()
    ok, error_resp = EvidenceValidator.validate_file_upload(
        file.content_type, len(data), allowed_mimetypes, max_size_mb
    )
    
    if not ok:
        raise HTTPException(status_code=415, detail=error_resp.model_dump())
    
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding("authenticity", "", [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        "authenticity", raw.get("finding") or f"Authenticity analysis: {file.filename or 'upload'}.",
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    result.setdefault("metadata", {})["forensicMode"] = "signal-only"
    return _persist(request, "authenticity", {"filename": file.filename, "mimeType": file.content_type}, result) if request else result


# ── URL Endpoint (with clear error messages) ──

@router.post("/api/evidence/url")
async def url_evidence(request: Request, payload: dict):
    """Inspect and analyze a public URL for evidence extraction."""
    # Validate required URL field
    url = payload.get("url") or ""
    ok, error_resp = EvidenceValidator.validate_required_field(url, "url", "a URL")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    # Validate URL format
    url = url.strip()
    ok, error_resp = EvidenceValidator.validate_url(url)
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    # Sanitize URL
    url = storage.sanitize_url(url)
    if not url:
        raise HTTPException(status_code=400, detail=ErrorResponse(
            error=ErrorCode.INVALID_URL,
            message="Please enter a valid URL. It should start with 'http://' or 'https://'. For example: https://example.com",
            field="url"
        ).model_dump())
    
    claim = (payload.get("claim") or "").strip()
    inspection = await web_inspector.inspect_live_url(url)
    raw = await _ai_finding("web source", claim, [{"text": json.dumps(inspection or {})}])
    result = _envelope("url", raw.get("finding") or "Source inspected.", claim=claim,
                       observations=raw.get("observations"), facts=raw.get("facts"),
                       sources=[url], metadata={"inspection": inspection, "ai": raw})
    return _persist(request, "url", {"url": url, "claim": claim}, result)


# ── Structured Data Endpoint (with clear error messages) ──

@router.post("/api/evidence/structured")
async def structured_evidence(request: Request, file: UploadFile | None = File(None), payload: str = Form(""), claim: str = Form("")):
    """Analyze a JSON or CSV data source for evidence extraction."""
    # Validate at least one payload source
    if not payload.strip() and not file:
        raise HTTPException(status_code=400, detail=ErrorResponse(
            error=ErrorCode.MISSING_REQUIRED_FIELD,
            message="Please provide either a JSON/CSV file to upload, or paste the content directly. At least one is required.",
            field="payload"
        ).model_dump())
    
    content = payload
    if file is not None:
        # Validate file upload
        allowed_mimetypes = structured_contract().accepted_mimetypes
        max_size_mb = structured_contract().max_file_size_mb
        
        data = await file.read()
        ok, error_resp = EvidenceValidator.validate_file_upload(
            file.content_type, len(data), allowed_mimetypes, max_size_mb
        )
        
        if not ok:
            raise HTTPException(status_code=415, detail=error_resp.model_dump())
        
        content = data.decode("utf-8", errors="replace")
    
    if not content.strip():
        raise HTTPException(status_code=400, detail=ErrorResponse(
            error=ErrorCode.INVALID_JSON,
            message="Please provide either a JSON/CSV file to upload, or paste the content directly. At least one is required.",
            field="payload"
        ).model_dump())
    
    # Try to parse as JSON first
    try:
        parsed = json.loads(content)
        summary = {"kind": "json", "keys": list(parsed)[:50] if isinstance(parsed, dict) else [], "records": len(parsed) if isinstance(parsed, list) else 1}
    except json.JSONDecodeError:
        # Try CSV
        try:
            rows = list(csv.reader(io.StringIO(content)))
            summary = {"kind": "csv", "columns": rows[0] if rows else [], "rows": max(0, len(rows) - 1)}
        except Exception:
            raise HTTPException(status_code=400, detail=ErrorResponse(
                error=ErrorCode.INVALID_CSV,
                message="The content is neither valid JSON nor valid CSV. Please check your format and try again.",
                field="payload"
            ).model_dump())
    
    return _persist(request, "structured", {"claim": claim, "summary": summary}, _envelope("structured", f"Structured data processed: {summary}.", claim=claim, metadata=summary))


# ── Evidence Analysis Endpoints (JSON-based with clear error messages) ──

@router.post("/api/evidence/assess")
async def assess_evidence(request: Request, payload: dict):
    """Assess a claim against supplied evidence."""
    # Validate evidence array
    evidence_payload = payload.get("evidence") or []
    
    ok, error_resp = EvidenceValidator.validate_required_field(evidence_payload, "evidence", "evidence items")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    ok, error_resp = EvidenceValidator.validate_evidence_array_length(evidence_payload, 1, "evidence assessment")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    # Check all evidence items are usable (have status "extracted")
    if not all(isinstance(e, dict) and e.get("status") == "extracted" for e in evidence_payload):
        raise HTTPException(status_code=400, detail=ErrorResponse(
            error=ErrorCode.INVALID_BODY_SCHEMA,
            message="All evidence items must have status 'extracted'. Please make sure your evidence items are properly extracted before submitting.",
            field="evidence"
        ).model_dump())
    
    evidence = _refs(evidence_payload)
    result = heuristic_analysis({"question": payload.get("claim") or "", "evidenceRequirements": []}, evidence)
    return _persist(request, "assess", payload, {"type": "assessment", "claim": payload.get("claim") or "", "verdict": result["conclusion"], "confidence": result["confidence"] / 100, "findings": result["findings"], "limitations": result["limitations"]})


@router.post("/api/evidence/contradictions")
async def contradictions_evidence(request: Request, payload: dict):
    """Find contradictions in supplied evidence items."""
    # Validate evidence array has at least 2 items
    evidence_payload = payload.get("evidence") or []
    
    ok, error_resp = EvidenceValidator.validate_required_field(evidence_payload, "evidence", "evidence items")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    ok, error_resp = EvidenceValidator.validate_evidence_array_length(evidence_payload, 2, "contradiction detection")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    evidence = _refs(evidence_payload)
    pairs = []
    for left_index, left in enumerate(evidence):
        left_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", left["finding"])
        for right in evidence[left_index + 1:]:
            right_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", right["finding"])
            if left_numbers and right_numbers and left_numbers != right_numbers:
                pairs.append({"left": left["id"], "right": right["id"], "reason": "Different numeric observations."})
    return _persist(request, "contradictions", payload, {"type": "contradictions", "contradictions": pairs, "count": len(pairs)})


@router.post("/api/evidence/duplicates")
async def duplicates_evidence(request: Request, payload: dict):
    """Find duplicate and dependent evidence items."""
    evidence_payload = payload.get("evidence") or []
    
    ok, error_resp = EvidenceValidator.validate_required_field(evidence_payload, "evidence", "evidence items")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    evidence = _refs(evidence_payload)
    groups = {}
    for item in evidence:
        groups.setdefault(re.sub(r"\W+", " ", item["finding"].lower()).strip(), []).append(item["id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    return _persist(request, "duplicates", payload, {"type": "duplicates", "duplicates": duplicates, "independent_count": len(evidence) - sum(len(ids) - 1 for ids in duplicates)})


@router.post("/api/evidence/timeline")
async def timeline_evidence(request: Request, payload: dict):
    """Reconstruct a timeline from supplied evidence items."""
    evidence_payload = payload.get("evidence") or []
    
    ok, error_resp = EvidenceValidator.validate_required_field(evidence_payload, "evidence", "evidence items")
    if not ok:
        raise HTTPException(status_code=400, detail=error_resp.model_dump())
    
    events = []
    for item in evidence_payload:
        if not isinstance(item, dict):
            continue
        dates = re.findall(r"\b(?:19|20)\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?\b", json.dumps(item))
        events.extend({"date": date, "evidence_id": item.get("evidence_id") or item.get("id"), "text": item.get("text") or item.get("finding", "")} for date in dates)
    return _persist(request, "timeline", payload, {"type": "timeline", "events": events})


@router.post("/api/evidence/gaps")
async def gaps_evidence(request: Request, payload: dict):
    """Identify missing evidence and unresolved questions."""
    evidence_payload = payload.get("evidence") or []
    
    # For gaps endpoint, empty evidence is acceptable (it helps identify what's missing)
    if evidence_payload is None or not isinstance(evidence_payload, list):
        raise HTTPException(status_code=400, detail=ErrorResponse(
            error=ErrorCode.INVALID_BODY_SCHEMA,
            message="The evidence must be a list of items. Please make sure you're sending an array.",
            field="evidence"
        ).model_dump())
    
    return _persist(request, "gaps", payload, {"type": "gaps", "status": "supported" if len(evidence_payload) >= 2 else "insufficient_evidence", "missing": [] if evidence_payload else ["independent evidence"], "unresolved_questions": [] if evidence_payload else [payload.get("claim") or "Provide evidence for this claim."]})


# ── Helper functions ──

def _refs(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("finding") or item.get("claim") or json.dumps(item)
        result.append({
            "id": item.get("evidence_id") or item.get("id") or _id(),
            "status": "collected",
            "type": item.get("type", "text"),
            "finding": text,
            "source": (item.get("sources") or ["submitted evidence"])[0],
            "confidence": item.get("confidence", 0),
            "signal": item.get("signal", "uncertain"),
            "metadata": item.get("metadata") or {}
        })
    return result
