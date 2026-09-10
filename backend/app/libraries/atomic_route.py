"""Shared atomic paid-route handler (mirrors x402/atomicRoute.ts)."""
import secrets
import json

from .. import db, config
from ..libraries import storage
from ..libraries import capabilities as caps


class InputValidationError(Exception):
    pass


def _nanoid(prefix, n=8):
    token = secrets.token_urlsafe(9)[:n]
    return f"{prefix}_{token}"


def _mime_to_input_type(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime == "application/pdf" or mime.startswith("text/"):
        return "document"
    if "json" in mime or "csv" in mime:
        return "data"
    return "document"


# Each capability owns a distinct set of input types — a video investigation
# rejects audio/image files, document accepts text-or-PDF, data accepts only
# CSV/JSON, and so on. Rejects mismatched uploads before any payment can run.
ALLOWED_INPUT_TYPES = {
    "claim-investigation": {"text", "url", "document"},
    "image-investigation": {"image"},
    "video-investigation": {"video"},
    "document-investigation": {"document", "text"},
    "source-investigation": {"url"},
    "data-investigation": {"data"},
    "audio-investigation": {"audio"},
}


async def parse_body(body: dict | None, files: list) -> dict:
    question = storage.sanitize_text((body or {}).get("question") or "")
    url = (body or {}).get("url") or ""
    text = storage.sanitize_text((body or {}).get("text") or "")
    service_name = storage.sanitize_text((body or {}).get("serviceName") or "")
    return {"question": question, "url": url, "text": text, "serviceName": service_name, "files": files}


def mime_to_base64(mime: str, data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


def _build_stored_inputs(parsed: dict, case_id: str) -> list[dict]:
    inputs = []
    if parsed.get("url"):
        sanitized = storage.sanitize_url(parsed["url"])
        if sanitized:
            inputs.append({"type": "url", "content": sanitized})
    if parsed.get("text"):
        inputs.append({"type": "text", "content": parsed["text"]})
    for file in parsed.get("files") or []:
        stored = storage.store_file(file["data"], file["name"], file["mime"], case_id)
        inputs.append({
            "type": _mime_to_input_type(file["mime"]),
            "content": file["name"],
            "fileName": stored["fileName"],
            "mimeType": stored["mimeType"],
            "filePath": stored["filePath"],
        })
    return inputs


async def handle_atomic_paid_request(capability_id: str, user, body, files, idempotency_key: str | None = None) -> dict:
    """Returns { status, content, headers }. Status 200 on success with the
    Investigation as content."""
    capability = config.get_paid_capability(capability_id)
    if not capability:
        return {"status": 400, "content": {"error": f"Unknown capability: {capability_id}"}}

    if idempotency_key:
        existing = db.get_investigation_by_idempotency_key(idempotency_key, user["id"])
        if existing:
            return {"status": 200, "content": {
                "id": existing["id"], "status": existing["status"],
                "capability": capability_id, "idempotent": True,
            }}

    try:
        parsed = await parse_body(body, files)
    except InputValidationError as e:
        return {"status": 400, "content": {"error": str(e)}}

    if not (parsed.get("question") or "").strip():
        return {"status": 400, "content": {"error": "Question is required"}}

    case_id = f"case_{secrets.token_urlsafe(6)[:10]}"
    inputs = _build_stored_inputs(parsed, case_id)

    # Capability-specific input assembly (mirrors assembleInputs).
    if capability_id == "source-investigation":
        has_url = any(i["type"] == "url" for i in inputs)
        if has_url and parsed.get("url"):
            # already captured via buildStoredInputs
            pass
        if not any(i["type"] == "url" for i in inputs):
            if parsed.get("url"):
                inputs.insert(0, {"type": "url", "content": storage.sanitize_url(parsed["url"])})
        if not any(i["type"] == "url" for i in inputs):
            return {"status": 400, "content": {"error": "source-investigation requires a valid URL"}}

    # Enforce per-capability input types (audio files only for audio, video
    # only for video, text-or-PDF for documents, ...). Catches mismatched
    # uploads before anything is paid for or run.
    allowed = ALLOWED_INPUT_TYPES.get(capability_id)
    bad = [i for i in inputs if i.get("type") not in allowed]
    if bad:
        kinds = ", ".join(sorted(allowed))
        detail = ", ".join(f"{i.get('fileName') or i.get('content') or i.get('type')}" for i in bad[:3])
        return {"status": 400, "content": {
            "error": f"{capability_id} only accepts {kinds} inputs. Incompatible file(s): {detail}",
            "acceptedInputTypes": sorted(allowed),
        }}

    # Capability execution. Payment gating (402 / verify / settle) is handled
    # by the x402 FastAPI middleware at the ASGI layer, not here.
    run = caps.CAPABILITY_RUNNERS.get(capability_id)
    if not run:
        return {"status": 400, "content": {"error": f"Unknown capability: {capability_id}"}}
    try:
        result = await run({
            "id": case_id, "userId": user["id"],
            "question": (parsed.get("question") or "").strip(),
            "inputs": inputs, "idempotencyKey": idempotency_key,
        })
    except caps.InputError as e:
        return {"status": 400, "content": {"error": str(e)}}

    # Restore capability fields overwritten by settle clone.
    inv = db.get_investigation(result["id"])
    if inv and not inv.get("capability"):
        inv["capability"] = capability_id
        inv["capabilityPriceUsdc"] = capability.get("priceUsdc")
        if idempotency_key:
            inv["idempotencyKey"] = idempotency_key
        db.save_investigation(inv)
    if inv and parsed.get("serviceName"):
        inv["requestedService"] = parsed["serviceName"]
        inv["title"] = parsed["serviceName"]
        db.save_investigation(inv)

    return {"status": 200, "content": inv or result}