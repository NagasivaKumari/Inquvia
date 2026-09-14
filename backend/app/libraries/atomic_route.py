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
    return config.mime_input_type(mime)


ALLOWED_INPUT_TYPES = config.ATOMIC_INPUT_TYPES


async def parse_body(body: dict | None, files: list) -> dict:
    question = storage.sanitize_text((body or {}).get("question") or "")
    url = (body or {}).get("url") or ""
    text = storage.sanitize_text((body or {}).get("text") or "")
    service_name = storage.sanitize_text((body or {}).get("serviceName") or "")
    medical_opt_in = str((body or {}).get("medicalOptIn") or "").lower() in ("1", "true", "yes")
    return {
        "question": question, "url": url, "text": text, "serviceName": service_name,
        "files": files, "medicalOptIn": medical_opt_in,
    }


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


def _build_reused_inputs(parsed: dict, case_id: str, source: dict, files: list) -> list[dict]:
    """Reinvestigation inputs: reuse the source investigation's evidence
    without re-uploading it. Replacement url/text/files override the source."""
    source_inputs = source.get("inputs") or []
    inputs = []
    url = storage.sanitize_url(parsed.get("url") or "")
    if url:
        inputs.append({"type": "url", "content": url, "reusedFrom": source.get("id")})
    else:
        src_url = next((i.get("content") for i in source_inputs if i.get("type") == "url"), "")
        if src_url:
            inputs.append({"type": "url", "content": src_url, "reusedFrom": source.get("id")})
    text = parsed.get("text") or ""
    if text:
        inputs.append({"type": "text", "content": text, "reusedFrom": source.get("id")})
    else:
        src_text = next((i.get("content") for i in source_inputs if i.get("type") == "text"), "")
        if src_text:
            inputs.append({"type": "text", "content": src_text, "reusedFrom": source.get("id")})
    if files:
        for file in files:
            stored = storage.store_file(file["data"], file["name"], file["mime"], case_id)
            inputs.append({
                "type": _mime_to_input_type(file["mime"]),
                "content": file["name"],
                "fileName": stored["fileName"],
                "mimeType": stored["mimeType"],
                "filePath": stored["filePath"],
                "reusedFrom": source.get("id"),
            })
    else:
        for i in source_inputs:
            if i.get("filePath"):
                inputs.append({
                    "type": i.get("type") or _mime_to_input_type(i.get("mimeType") or ""),
                    "content": i.get("fileName") or i.get("content") or "evidence",
                    "fileName": i.get("fileName"),
                    "mimeType": i.get("mimeType"),
                    "filePath": i.get("filePath"),
                    "reusedFrom": source.get("id"),
                })
    return inputs


async def handle_atomic_paid_request(capability_id: str, user, body, files, idempotency_key: str | None = None, background_tasks=None, reuse_source: dict | None = None) -> dict:
    """Returns { status, content, headers }. Status 200 on success with the
    Investigation as content. When reuse_source (a previous investigation owned
    by the user) is given, its uploaded evidence is reused for a new paid run."""
    capability = config.get_paid_capability(capability_id)
    if not capability:
        return {"status": 400, "content": {"error": f"Unknown capability: {capability_id}", "errorCode": "UNKNOWN_CAPABILITY"}}

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
        print(f"DEBUG: InputValidationError: {e}")
        return {"status": 400, "content": {"error": str(e)}}

    if not (parsed.get("question") or "").strip():
        print(f"DEBUG: Missing question in parsed body: {parsed}")
        return {"status": 400, "content": {
            "error": "Please enter a question for your investigation.",
            "errorCode": "MISSING_REQUIRED_FIELD", "field": "question",
        }}

    case_id = f"case_{secrets.token_urlsafe(6)[:10]}"
    if reuse_source:
        inputs = _build_reused_inputs(parsed, case_id, reuse_source, files)
    else:
        inputs = _build_stored_inputs(parsed, case_id)
    allowed = ALLOWED_INPUT_TYPES.get(capability_id)
    if reuse_source and allowed:
        # Drop any reused inputs this capability does not accept, so a
        # mismatched source never drags an incompatible slot along.
        inputs = [i for i in inputs if i.get("type") in allowed]

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
    if capability_id == "image-investigation":
        image_count = sum(1 for i in inputs if i.get("type") == "image")
        if image_count > config.MAX_IMAGE_INPUTS:
            return {"status": 400, "content": {
                "error": f"image-investigation accepts at most {config.MAX_IMAGE_INPUTS} image(s); "
                         f"{image_count} were submitted.",
                "errorCode": "TOO_MANY_FILES",
                "field": "files",
                "maxImages": config.MAX_IMAGE_INPUTS,
            }}
    if capability_id == "image-batch-investigation":
        image_count = sum(1 for i in inputs if i.get("type") == "image")
        if image_count < 2:
            return {"status": 400, "content": {
                "error": "image-batch-investigation requires at least 2 images.",
                "errorCode": "TOO_FEW_FILES",
                "field": "files",
            }}
        if image_count > config.MAX_BATCH_IMAGE_INPUTS:
            return {"status": 400, "content": {
                "error": f"image-batch-investigation accepts at most {config.MAX_BATCH_IMAGE_INPUTS} images; "
                         f"{image_count} were submitted.",
                "errorCode": "TOO_MANY_FILES",
                "field": "files",
                "maxImages": config.MAX_BATCH_IMAGE_INPUTS,
            }}

    bad = [i for i in inputs if i.get("type") not in allowed]
    if bad:
        kinds = ", ".join(sorted(allowed))
        detail = ", ".join(f"{i.get('fileName') or i.get('content') or i.get('type')}" for i in bad[:3])
        accepted_exts = config.capability_accepted_extensions(capability_id)
        accepted_mimes = config.capability_accepted_mimes(capability_id)
        if accepted_exts:
            hint = "This endpoint accepts: " + ", ".join(e.lstrip(".").upper() for e in accepted_exts) + " files."
        else:
            hint = "This endpoint does not accept file uploads."
        return {"status": 400, "content": {
            "error": f"{capability_id} only accepts {kinds} inputs. Incompatible file(s): {detail}. {hint}",
            "errorCode": "UNSUPPORTED_FILE_TYPE", "field": "files",
            "acceptedInputTypes": sorted(allowed),
            "acceptedFileExtensions": accepted_exts,
            "acceptedMimeTypes": accepted_mimes,
            "maxFileSizeMB": config.MAX_UPLOAD_SIZE_MB,
        }}

    # Capability execution. Payment gating (402 / verify / settle) is handled
    # by the x402 FastAPI middleware at the ASGI layer, not here.
    run = caps.CAPABILITY_RUNNERS.get(capability_id)
    if not run:
        return {"status": 400, "content": {"error": f"Unknown capability: {capability_id}"}}
    try:
        run_args = {
            "id": case_id, "userId": user["id"],
            "question": (parsed.get("question") or "").strip(),
            "inputs": inputs, "idempotencyKey": idempotency_key,
            "medicalOptIn": parsed.get("medicalOptIn", False),
        }
        if capability_id == "video-investigation" and background_tasks:
            run_args["background_tasks"] = background_tasks

        result = await run(run_args)
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
    if reuse_source and inv:
        inv["reinvestigationOf"] = reuse_source.get("id")
        db.save_investigation(inv)

    return {"status": 200, "content": inv or result}