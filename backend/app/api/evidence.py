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

from fastapi import APIRouter, File, Form, Request, UploadFile

from .. import db
from ..libraries import ai, storage, web_inspector
from ..libraries.analyze import heuristic_analysis
from ..libraries.evidence_types import EvidenceResult

router = APIRouter()

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


async def _media(kind: str, file: UploadFile, claim: str = "", request: Request | None = None) -> dict:
    data = await file.read()
    ok, error = storage.validate_upload(file.content_type or "", len(data))
    if not ok:
        result = {"error": error}
        return _persist(request, kind, {"claim": claim, "filename": file.filename}, result) if request else result
    upload_ref = storage.store_file(data, file.filename or "upload.bin", file.content_type or "application/octet-stream", _id("case"))
    raw = await _ai_finding(kind, claim, [{"file": {"mimeType": file.content_type or "application/octet-stream", "base64": __import__("base64").b64encode(data).decode("ascii")}}])
    result = _envelope(
        kind, raw.get("finding") or f"{kind.title()} processed: {file.filename or 'upload'}.",
        claim=claim, facts=raw.get("facts"), observations=raw.get("observations"),
        metadata={"filename": file.filename, "mimeType": file.content_type,
                  "size": len(data), "filePath": upload_ref["filePath"], "ai": raw},
    )
    return _persist(request, kind, {"claim": claim, "filename": file.filename, "mimeType": file.content_type}, result) if request else result


@router.post("/api/evidence/image")
async def image_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    return await _media("image", file, claim, request)


@router.post("/api/evidence/video")
async def video_evidence(request: Request, file: UploadFile = File(...), claim: str = Form(""), max_frames: int = Form(8)):
    result = await _media("video", file, claim, request)
    if "metadata" in result:
        result["metadata"]["maxFrames"] = max(2, min(40, max_frames))
    return result


@router.post("/api/evidence/audio")
async def audio_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    return await _media("audio", file, claim, request)


@router.post("/api/evidence/document")
async def document_evidence(request: Request, file: UploadFile = File(...), claim: str = Form("")):
    return await _media("document", file, claim, request)


@router.post("/api/evidence/authenticity")
async def authenticity_evidence(request: Request, file: UploadFile = File(...)):
    result = await _media("authenticity", file, request=request)
    result.setdefault("metadata", {})["forensicMode"] = "signal-only"
    return result


@router.post("/api/evidence/url")
async def url_evidence(request: Request, payload: dict):
    url = storage.sanitize_url(payload.get("url") or "")
    if not url:
        return _persist(request, "url", payload, {"error": "A valid URL is required"})
    claim = (payload.get("claim") or "").strip()
    inspection = await web_inspector.inspect_live_url(url)
    raw = await _ai_finding("web source", claim, [{"text": json.dumps(inspection or {})}])
    result = _envelope("url", raw.get("finding") or "Source inspected.", claim=claim,
                       observations=raw.get("observations"), facts=raw.get("facts"),
                       sources=[url], metadata={"inspection": inspection, "ai": raw})
    return _persist(request, "url", {"url": url, "claim": claim}, result)


@router.post("/api/evidence/structured")
async def structured_evidence(request: Request, file: UploadFile | None = File(None), payload: str = Form(""), claim: str = Form("")):
    content = payload
    if file is not None:
        data = await file.read()
        ok, error = storage.validate_upload(file.content_type or "", len(data))
        if not ok:
            return _persist(request, "structured", {"claim": claim, "filename": file.filename}, {"error": error})
        content = data.decode("utf-8", errors="replace")
    if not content:
        return _persist(request, "structured", {"claim": claim}, {"error": "A JSON payload or file is required"})
    try:
        parsed = json.loads(content)
        summary = {"kind": "json", "keys": list(parsed)[:50] if isinstance(parsed, dict) else [], "records": len(parsed) if isinstance(parsed, list) else 1}
    except json.JSONDecodeError:
        rows = list(csv.reader(io.StringIO(content)))
        summary = {"kind": "csv", "columns": rows[0] if rows else [], "rows": max(0, len(rows) - 1)}
    return _persist(request, "structured", {"claim": claim, "summary": summary}, _envelope("structured", f"Structured data processed: {summary}.", claim=claim, metadata=summary))


def _refs(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        text = item.get("text") or item.get("finding") or item.get("claim") or json.dumps(item)
        result.append({"id": item.get("evidence_id") or item.get("id") or _id(), "status": "collected", "type": item.get("type", "text"), "finding": text, "source": (item.get("sources") or ["submitted evidence"])[0], "confidence": item.get("confidence", 0), "signal": item.get("signal", "uncertain"), "metadata": item.get("metadata") or {}})
    return result


@router.post("/api/evidence/assess")
async def assess_evidence(request: Request, payload: dict):
    # Enforce Hard Gate: Ensure all evidence is usable
    evidence_payload = payload.get("evidence") or []
    # If using EvidenceResult, convert to dict for analysis if needed, 
    # but check usability first.
    if not all(isinstance(e, dict) and e.get("status") == "extracted" for e in evidence_payload):
         return _persist(request, "assess", payload, {"error": "Insufficient or unusable evidence for assessment"})
         
    evidence = _refs(evidence_payload)
    result = heuristic_analysis({"question": payload.get("claim") or "", "evidenceRequirements": []}, evidence)
    return _persist(request, "assess", payload, {"type": "assessment", "claim": payload.get("claim") or "", "verdict": result["conclusion"], "confidence": result["confidence"] / 100, "findings": result["findings"], "limitations": result["limitations"]})


@router.post("/api/evidence/contradictions")
async def contradictions_evidence(request: Request, payload: dict):
    evidence = _refs(payload.get("evidence") or [])
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
    evidence = _refs(payload.get("evidence") or [])
    groups = {}
    for item in evidence:
        groups.setdefault(re.sub(r"\W+", " ", item["finding"].lower()).strip(), []).append(item["id"])
    duplicates = [ids for ids in groups.values() if len(ids) > 1]
    return _persist(request, "duplicates", payload, {"type": "duplicates", "duplicates": duplicates, "independent_count": len(evidence) - sum(len(ids) - 1 for ids in duplicates)})


@router.post("/api/evidence/timeline")
async def timeline_evidence(request: Request, payload: dict):
    events = []
    for item in payload.get("evidence") or []:
        dates = re.findall(r"\b(?:19|20)\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?\b", json.dumps(item))
        events.extend({"date": date, "evidence_id": item.get("evidence_id") or item.get("id"), "text": item.get("text") or item.get("finding", "")} for date in dates)
    return _persist(request, "timeline", payload, {"type": "timeline", "events": events})


@router.post("/api/evidence/gaps")
async def gaps_evidence(request: Request, payload: dict):
    evidence = payload.get("evidence") or []
    return _persist(request, "gaps", payload, {"type": "gaps", "status": "supported" if len(evidence) >= 2 else "insufficient_evidence", "missing": [] if evidence else ["independent evidence"], "unresolved_questions": [] if evidence else [payload.get("claim") or "Provide evidence for this claim."]})