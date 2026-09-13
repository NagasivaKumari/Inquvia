"""MongoDB-backed storage for investigation inputs."""
import shutil
from pathlib import Path

from .. import config, db


class InputValidationError(Exception):
    pass


def sanitize_text(text: str) -> str:
    return (text or "").strip()


def sanitize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    # Accept bare domains users commonly paste into the form.
    if "." in url and " " not in url and not url.startswith("/"):
        return f"https://{url}"
    return ""


def validation_error(message: str, code: str | None = None, field: str | None = None, details: dict | None = None) -> dict:
    """Structured validation error preserving a machine-readable code + human message."""
    resp = {"error": message}
    if code:
        resp["errorCode"] = code
    if field:
        resp["field"] = field
    if details:
        resp["details"] = details
    return resp


def _accepted_extensions_hint(capability_id: str | None) -> str | None:
    exts = config.capability_accepted_extensions(capability_id) if capability_id else []
    if exts:
        return "This endpoint accepts: " + ", ".join(e.lstrip(".").upper() for e in exts) + " files."
    return None


def validate_upload(mime: str, size: int, filename: str = "upload.bin", capability_id: str | None = None) -> tuple[bool, dict | None]:
    safe_name = Path(filename).name or "upload.bin"
    if size <= 0:
        return False, validation_error(
            f'"{safe_name}" is empty. Please choose a file that has content.',
            "INVALID_FIELD_VALUE", "files",
        )
    if size > config.MAX_UPLOAD_SIZE:
        return False, validation_error(
            f'"{safe_name}" is too large. The maximum allowed size is {config.MAX_UPLOAD_SIZE_MB}MB.',
            "FILE_TOO_LARGE", "files",
            {"maxSizeMB": config.MAX_UPLOAD_SIZE_MB, "receivedSizeBytes": size},
        )
    if mime not in config.ALLOWED_MIME:
        hint = _accepted_extensions_hint(capability_id)
        message = f'"{safe_name}" is not a supported file type.'
        if hint:
            message += " " + hint
        else:
            accepted = ", ".join(sorted({ext.lstrip(".").upper() for m in config.ALLOWED_MIME for ext in config.MIME_EXTENSIONS.get(m, [])}))
            message += f" Supported types: {accepted}."
        details = {
            "maxSizeMB": config.MAX_UPLOAD_SIZE_MB,
            "acceptedFileExtensions": config.capability_accepted_extensions(capability_id) if capability_id else [],
            "acceptedMimeTypes": config.capability_accepted_mimes(capability_id) if capability_id else list(config.ALLOWED_MIME),
        }
        return False, validation_error(message, "UNSUPPORTED_FILE_TYPE", "files", details)
    return True, None


def store_file(data: bytes, filename: str, mime: str, case_id: str) -> dict:
    safe_name = Path(filename).name or "upload.bin"
    file_id = db.store_upload_file(data, safe_name, mime, case_id)
    return {"fileName": safe_name, "mimeType": mime, "filePath": file_id, "size": len(data)}


def resolve_stored_path(file_path: str) -> Path | None:
    if file_path.startswith("gridfs:"):
        return None
    p = (config.STORAGE_PATH / file_path).resolve()
    if not p.is_file():
        return None
    return p


def _is_binary_mime(mime: str | None) -> bool:
    if not mime:
        return False
    mime = mime.lower()
    if mime.startswith(("image/", "video/", "audio/")):
        return True
    return mime in (
        "application/pdf",
        "application/octet-stream",
        "application/zip",
        "application/x-zip-compressed",
    )


def read_stored_text(file_path: str, max_chars: int = 60000) -> str | None:
    stored = db.read_upload_file(file_path)
    buf = stored[0] if stored else None
    mime = stored[1] if stored else None
    if buf is None:
        p = resolve_stored_path(file_path)
        if p:
            try:
                buf = p.read_bytes()
            except OSError:
                buf = None
    if buf is None:
        return None
    try:
        if len(buf) > 2 * 1024 * 1024:
            return None
        if _is_binary_mime(mime):
            return None
        import re
        text = buf.decode("utf-8", errors="ignore")
        # Binary data that slipped past the mime check still decodes to garbage
        # (control chars / NUL bytes); treat it as non-text so it is never fed
        # to the AI as if it were readable evidence.
        if re.search(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", text):
            return None
        return text[:max_chars]
    except Exception:
        return None


def read_stored_file_base64(file_path: str) -> dict | None:
    stored = db.read_upload_file(file_path)
    buf = stored[0] if stored else None
    mime = stored[1] if stored else None
    if buf is None:
        p = resolve_stored_path(file_path)
        if p:
            try:
                buf = p.read_bytes()
            except OSError:
                buf = None
    if buf is None:
        return None
    try:
        if len(buf) == 0 or len(buf) > 8 * 1024 * 1024:
            return None
        import base64
        return {"mimeType": mime or _guess_mime(file_path), "base64": base64.b64encode(buf).decode("ascii")}
    except Exception:
        return None


def _guess_mime(file_path: str) -> str:
    l = file_path.lower()
    if l.endswith(".pdf"):
        return "application/pdf"
    if l.endswith(".mp4"):
        return "video/mp4"
    if l.endswith(".webm"):
        return "video/webm"
    if l.endswith(".gif"):
        return "image/gif"
    if l.endswith(".png"):
        return "image/png"
    if l.endswith(".webp"):
        return "image/webp"
    if l.endswith(".json"):
        return "application/json"
    if l.endswith(".csv") or l.endswith(".txt"):
        return "text/plain"
    return "image/jpeg"


def cleanup_case(case_id: str) -> None:
    db.delete_uploads_for_case(case_id)
    shutil.rmtree(config.STORAGE_PATH / case_id, ignore_errors=True)