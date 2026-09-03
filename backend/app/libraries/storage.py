"""File storage for investigation inputs (mirrors src/lib/storage)."""
import shutil
from pathlib import Path

from .. import config


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


def validate_upload(mime: str, size: int) -> tuple[bool, str | None]:
    if size <= 0:
        return False, "File is empty"
    if size > config.MAX_UPLOAD_SIZE:
        return False, "File exceeds the 10MB upload limit"
    if mime not in config.ALLOWED_MIME:
        return False, "File type not supported"
    return True, None


def store_file(data: bytes, filename: str, mime: str, case_id: str) -> dict:
    case_dir = config.STORAGE_PATH / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "upload.bin"
    file_path = case_dir / safe_name
    file_path.write_bytes(data)
    rel = str(file_path.relative_to(config.STORAGE_PATH)).replace("\\", "/")
    return {"fileName": safe_name, "mimeType": mime, "filePath": rel}


def resolve_stored_path(file_path: str) -> Path | None:
    p = (config.STORAGE_PATH / file_path).resolve()
    if not p.is_file():
        return None
    return p


def read_stored_text(file_path: str, max_chars: int = 60000) -> str | None:
    p = resolve_stored_path(file_path)
    if not p:
        return None
    try:
        buf = p.read_bytes()
        if len(buf) > 2 * 1024 * 1024:
            return None
        import re
        text = buf.decode("utf-8", errors="ignore")
        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)
        return text[:max_chars]
    except Exception:
        return None


def read_stored_file_base64(file_path: str) -> dict | None:
    p = resolve_stored_path(file_path)
    if not p:
        return None
    try:
        buf = p.read_bytes()
        if len(buf) == 0 or len(buf) > 8 * 1024 * 1024:
            return None
        import base64
        return {"mimeType": _guess_mime(file_path), "base64": base64.b64encode(buf).decode("ascii")}
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
    shutil.rmtree(config.STORAGE_PATH / case_id, ignore_errors=True)