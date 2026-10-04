"""Shared atomic paid-route handler (mirrors x402/atomicRoute.ts)."""
import secrets
import json
import logging

from .. import db, config
from ..libraries import storage
from ..libraries import source_input
from ..libraries import capabilities as caps
from ..libraries import engine

logger = logging.getLogger(__name__)


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
    url = (body or {}).get("url") or (body or {}).get("urls") or ""
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
    body_url = parsed.get("url") or parsed.get("urls") or ""
    raw_urls = []
    if isinstance(body_url, list):
        raw_urls.extend(body_url)
    elif isinstance(body_url, str):
        raw_urls.extend([u.strip() for u in body_url.replace(",", "\n").split("\n") if u.strip()])
    for u in raw_urls:
        sanitized = storage.sanitize_url(u)
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


def _remote_allowed_mimes(capability_id: str) -> set[str]:
    accepted = set(config.capability_accepted_mimes(capability_id))
    candidates = set(source_input.ANALYSIS_MIMES) | accepted
    if capability_id in ("source-investigation", "claim-investigation"):
        return candidates
    allowed_types = {t for t in ALLOWED_INPUT_TYPES.get(capability_id, set()) if t != "url"}
    result = {mime for mime in candidates if config.mime_input_type(mime, capability_id) in allowed_types}
    if capability_id not in (
        "image-investigation", "image-batch-investigation",
        "video-investigation", "audio-investigation",
    ):
        result.update(source_input.HTML_MIMES)
    return result


def _remote_expected_kind(capability_id: str) -> str | None:
    if capability_id in ("image-investigation", "image-batch-investigation"):
        return "image"
    if capability_id == "video-investigation":
        return "video"
    if capability_id == "audio-investigation":
        return "audio"
    return None


def _split_urls(value: object) -> list[str]:
    if isinstance(value, list):
        raw_urls = value
    elif isinstance(value, str):
        raw_urls = value.replace(",", "\n").splitlines()
    else:
        raw_urls = []
    return [url.strip() for url in raw_urls if isinstance(url, str) and url.strip()]


def _normalize_files(files: list[dict] | None) -> list[dict]:
    normalized = []
    for file in files or []:
        data = file.get("data") or b""
        name = file.get("name") or file.get("filename") or "upload.bin"
        mime = source_input.normalize_upload_mime(data, file.get("mime") or file.get("content_type"), name)
        source_input.validate_upload_mime(data, mime, "files")
        normalized.append({"data": data, "name": name, "mime": mime})
    return normalized


def _store_local_files(files: list[dict], case_id: str, reused_from: str | None = None) -> list[dict]:
    inputs = []
    for file in files or []:
        stored = storage.store_file(file["data"], file["name"], file["mime"], case_id)
        inputs.append({
            "type": _mime_to_input_type(file["mime"]),
            "content": file["name"],
            "fileName": stored["fileName"],
            "mimeType": stored["mimeType"],
            "filePath": stored["filePath"],
            **({"reusedFrom": reused_from} if reused_from else {}),
        })
    return inputs


async def _remote_input(
    url: str,
    case_id: str,
    capability_id: str,
    reused_from: str | None = None,
) -> dict:
    sanitized = storage.sanitize_url(url)
    if not sanitized:
        raise source_input.SourceInputError(400, "INVALID_URL", "Please enter a valid HTTP or HTTPS URL.", "url")
    expected_kind = _remote_expected_kind(capability_id)
    fetch_kwargs = (
        {"expected_kind": expected_kind} if expected_kind else {}
    )
    remote = await source_input.fetch_url(
        sanitized, _remote_allowed_mimes(capability_id), **fetch_kwargs
    )
    inspection = source_input.inspect_source(remote)
    original_source_url = sanitized
    source_page_inspection = inspection

    # A document investigation submitted as a landing page must analyze the
    # report, not just the page's availability or summary text. Prefer a
    # downloadable PDF advertised by the page and retain the landing page as
    # provenance for the resulting document input.
    if capability_id == "document-investigation" and remote.mime_type in source_input.HTML_MIMES:
        links = inspection.get("links") or []
        pdf_links = []
        for link in links:
            href = str((link or {}).get("href") or "").strip()
            text = str((link or {}).get("text") or "").lower()
            if href and (href.lower().split("?", 1)[0].endswith(".pdf") or "pdf" in text):
                if href not in pdf_links:
                    pdf_links.append(href)
        for pdf_url in pdf_links:
            try:
                candidate = await source_input.fetch_url(pdf_url, {"application/pdf"})
            except source_input.SourceInputError:
                continue
            if candidate.mime_type == "application/pdf":
                logger.info(
                    "document-investigation: promoted downloadable report PDF "
                    "from source page %s to document evidence",
                    original_source_url,
                )
                remote = candidate
                inspection = source_input.inspect_source(remote)
                inspection["sourcePageUrl"] = original_source_url
                inspection["sourcePageInspection"] = source_page_inspection
                break

    input_type = "url" if capability_id == "source-investigation" else None
    result = source_input.store_remote_input(
        remote,
        case_id,
        capability_id=capability_id,
        input_type=input_type,
        reused_from=reused_from,
        inspection=inspection,
    )
    if capability_id == "document-investigation" and original_source_url != remote.requested_url:
        result["sourcePageUrl"] = original_source_url
        result["sourcePageInspection"] = inspection.get("sourcePageInspection")
    return result


async def _build_inputs_with_sources(
    parsed: dict,
    case_id: str,
    capability_id: str,
    files: list[dict],
    reuse_source: dict | None = None,
) -> list[dict]:
    urls = _split_urls(parsed.get("url"))
    if reuse_source:
        inputs = _build_reused_inputs(parsed, case_id, reuse_source, files)
        if urls:
            remotes = [
                await _remote_input(url, case_id, capability_id, reuse_source.get("id"))
                for url in urls
            ]
            inputs = [item for item in inputs if item.get("type") != "url"]
            inputs = remotes + inputs
        elif capability_id == "document-investigation":
            # Older document investigations stored a landing-page URL as a
            # URL input. Re-fetch it now so reinvestigation has a document
            # file to extract and analyze with the new question.
            source_url = next(
                (
                    i.get("content")
                    for i in (reuse_source.get("inputs") or [])
                    if i.get("type") == "url" and i.get("content")
                ),
                "",
            )
            if source_url:
                logger.info(
                    "document-investigation: refetching original URL %s for "
                    "reinvestigation %s",
                    source_url,
                    reuse_source.get("id"),
                )
                remote = await _remote_input(
                    source_url, case_id, capability_id, reuse_source.get("id")
                )
                inputs = [item for item in inputs if item.get("type") != "url"]
                inputs.insert(0, remote)
        return inputs

    inputs = []
    for url in urls:
        inputs.append(await _remote_input(url, case_id, capability_id))
    if parsed.get("text"):
        inputs.append({"type": "text", "content": parsed["text"]})
    inputs.extend(_store_local_files(files, case_id))
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
        normalized_files = _normalize_files(files)
    except source_input.SourceInputError as e:
        return {"status": e.status_code, "content": e.paid_content()}
    except InputValidationError as e:
        print(f"DEBUG: InputValidationError: {e}")
        return {"status": 400, "content": {"error": str(e)}}

    for file in normalized_files:
        ok, err = storage.validate_upload(file["mime"], len(file["data"]), file["name"], capability_id)
        if not ok:
            status = 413 if err.get("errorCode") == "FILE_TOO_LARGE" else 415 if err.get("errorCode") == "UNSUPPORTED_FILE_TYPE" else 400
            return {"status": status, "content": err}

    if not (parsed.get("question") or "").strip():
        print(f"DEBUG: Missing question in parsed body: {parsed}")
        return {"status": 400, "content": {
            "error": "Please enter a question for your investigation.",
            "errorCode": "MISSING_REQUIRED_FIELD", "field": "question",
        }}

    case_id = f"case_{secrets.token_urlsafe(6)[:10]}"
    try:
        inputs = await _build_inputs_with_sources(
            parsed, case_id, capability_id, normalized_files, reuse_source=reuse_source,
        )
    except source_input.SourceInputError as e:
        print(f"DEBUG: Source input rejected for {capability_id}: {e.code} - {e.message}")
        return {"status": e.status_code, "content": e.paid_content()}
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
    run_args = {
        "id": case_id, "userId": user["id"],
        "question": (parsed.get("question") or "").strip(),
        "inputs": inputs, "idempotencyKey": idempotency_key,
        "medicalOptIn": parsed.get("medicalOptIn", False),
    }
    if capability_id == "video-investigation" and background_tasks:
        run_args["background_tasks"] = background_tasks

    if background_tasks and capability_id != "video-investigation":
        pending = engine.start_capability_investigation({
            **run_args,
            "title": capability.get("title") or "Investigation in Progress",
            "capability": capability_id,
        })
        pending["status"] = "queued"
        pending["currentStage"] = "created"
        db.save_investigation(pending)
        background_tasks.add_task(
            _run_capability_background,
            run,
            run_args,
            capability_id,
            capability.get("priceUsdc"),
            parsed.get("serviceName"),
            reuse_source,
        )
        return {"status": 200, "content": pending}

    try:
        result = await run(run_args)
    except caps.InputError as e:
        return {"status": 400, "content": {"error": str(e)}}

    inv = _restore_run_metadata(
        result, capability_id, capability.get("priceUsdc"), idempotency_key,
        parsed.get("serviceName"), reuse_source,
    )
    return {"status": 200, "content": inv or result}


def _restore_run_metadata(
    result: dict,
    capability_id: str,
    price_usdc,
    idempotency_key: str | None,
    service_name: str | None,
    reuse_source: dict | None,
) -> dict | None:
    """Restore request metadata after a capability runner saves its result."""
    inv = db.get_investigation(result["id"])
    if inv:
        identity = config.get_capability_metadata(
            inv.get("originalCapabilityId") or inv.get("capabilityId")
            or inv.get("capability") or capability_id
        )
        inv["capability"] = identity["capabilityId"]
        inv["capabilityId"] = identity["capabilityId"]
        inv["serviceName"] = inv.get("originalServiceName") or identity["serviceName"]
        inv["originalCapabilityId"] = inv.get("originalCapabilityId") or identity["capabilityId"]
        inv["originalServiceName"] = inv.get("originalServiceName") or identity["serviceName"]
        inv["capabilityPriceUsdc"] = price_usdc
        if idempotency_key:
            inv["idempotencyKey"] = idempotency_key
        db.save_investigation(inv)
    if inv:
        # A request label is not authoritative case identity. Keep it only as
        # audit context and never let it rewrite the original capability.
        if service_name:
            inv["requestedService"] = service_name
        inv["title"] = inv.get("originalServiceName") or inv.get("serviceName")
        db.save_investigation(inv)
    if reuse_source and inv:
        inv["reinvestigationOf"] = reuse_source.get("id")
        inv["parentCaseId"] = reuse_source.get("id")
        inv["originalCapabilityId"] = (
            reuse_source.get("originalCapabilityId")
            or reuse_source.get("capabilityId")
            or reuse_source.get("capability")
            or inv.get("capability")
        )
        inv["capabilityId"] = inv["originalCapabilityId"]
        inv["capability"] = inv["originalCapabilityId"]
        inv["originalServiceName"] = (
            reuse_source.get("originalServiceName")
            or reuse_source.get("serviceName")
            or config.get_capability_metadata(inv["originalCapabilityId"])["serviceName"]
        )
        inv["serviceName"] = inv["originalServiceName"]
        inv["title"] = inv["originalServiceName"]
        inv["originalQuestion"] = (
            reuse_source.get("originalQuestion")
            or reuse_source.get("question")
        )
        inv["originalInputs"] = reuse_source.get("originalInputs") or reuse_source.get("inputs") or []
        db.save_investigation(inv)
    return inv


async def _run_capability_background(
    run,
    run_args: dict,
    capability_id: str,
    price_usdc,
    service_name: str | None,
    reuse_source: dict | None,
) -> None:
    try:
        result = await run(run_args)
        _restore_run_metadata(
            result, capability_id, price_usdc, run_args.get("idempotencyKey"),
            service_name, reuse_source,
        )
    except caps.InputError as exc:
        inv = db.get_investigation(run_args["id"])
        if inv:
            inv["status"] = "failed"
            inv["limitations"] = [str(exc)]
            db.save_investigation(inv)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        inv = db.get_investigation(run_args["id"])
        if inv:
            inv["status"] = "failed"
            inv["limitations"] = [f"Processing failed: {exc}"]
            db.save_investigation(inv)