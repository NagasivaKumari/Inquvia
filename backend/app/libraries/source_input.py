import ipaddress
import json
import mimetypes
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

from .. import config
from . import document_extract, storage, web_inspector

MAX_REMOTE_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5
REMOTE_TIMEOUT_SECONDS = 10.0
REMOTE_CONNECT_TIMEOUT_SECONDS = 5.0
REMOTE_USER_AGENT = web_inspector.USER_AGENT

HTML_MIMES = {"text/html", "application/xhtml+xml"}
ANALYSIS_MIMES = HTML_MIMES | {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "application/json",
    "application/x-jsonlines",
    "application/xml",
    "text/xml",
}


class SourceInputError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field: str = "url", details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.details = details or {}
        self.content = {"error": code, "errorCode": code, "message": message, "field": field}
        if self.details:
            self.content["details"] = self.details
        super().__init__(message)

    def paid_content(self) -> dict:
        result = {"error": self.message, "errorCode": self.code, "field": self.field}
        if self.details:
            result["details"] = self.details
        return result


@dataclass
class RemoteSource:
    data: bytes
    requested_url: str
    final_url: str
    filename: str
    mime_type: str
    declared_mime: str
    status_code: int
    redirects: int
    resolved_ips: list[str]
    connected_ip: str
    encoding: str | None = None


def _content_type(value: str | None) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF-")


def normalize_upload_mime(data: bytes, declared: str | None, filename: str = "") -> str:
    if is_pdf(data):
        return "application/pdf"
    mime = _content_type(declared)
    if mime and mime != "application/octet-stream":
        return mime
    guessed = mimetypes.guess_type(filename)[0] if filename else None
    return _content_type(guessed) or mime or "application/octet-stream"


def validate_upload_mime(data: bytes, mime: str, field: str = "file") -> None:
    validate_pdf(data, _content_type(mime), field)


def normalize_mime(data: bytes, declared: str | None, url: str = "") -> str:
    if is_pdf(data):
        return "application/pdf"
    sniffed = _sniff_media_mime(data)
    if sniffed:
        return sniffed
    mime = _content_type(declared)
    if mime and mime not in ("application/octet-stream", "text/plain"):
        return mime
    guessed = mimetypes.guess_type(urlsplit(url).path)[0] if url else None
    if guessed:
        return _content_type(guessed)
    sample = data[:4096].lstrip().lower()
    if sample.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    if sample.startswith((b"{", b"[")):
        return "application/json"
    if data and b"\x00" not in data:
        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    return mime or "application/octet-stream"


def _sniff_media_mime(data: bytes) -> str | None:
    """Identify common media from signatures when headers are generic/wrong."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith(b"RIFF") and len(data) >= 12:
        if data[8:12] == b"WEBP":
            return "image/webp"
        if data[8:12] == b"WAVE":
            return "audio/wav"
        if data[8:12] == b"AVI ":
            return "video/x-msvideo"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"ID3") or _looks_like_mp3_frame(data):
        return "audio/mpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"qt  ",):
            return "video/quicktime"
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio/mp4"
        return "video/mp4"
    if data.startswith((b"\xff\xf1", b"\xff\xf9")):
        return "audio/aac"
    if data.startswith((b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3")):
        return "video/mpeg"
    return None


def _looks_like_mp3_frame(data: bytes) -> bool:
    if len(data) < 2 or data[0] != 0xFF:
        return False
    return (data[1] & 0xE0) == 0xE0 and (data[1] & 0x06) != 0


def validate_media_bytes(data: bytes, expected_kind: str, field: str = "url") -> None:
    """Reject HTML/text or corrupt bytes before a media pipeline runs."""
    kind = expected_kind.lower()
    mime = _sniff_media_mime(data)
    if kind == "image":
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(data)) as image:
                image.verify()
        except Exception as exc:
            raise SourceInputError(
                415, "REMOTE_INVALID_MEDIA",
                "The downloaded bytes are not a readable image.",
                field, {"expectedType": kind},
            ) from exc
        return
    if kind == "video" and (not mime or not mime.startswith("video/")):
        raise SourceInputError(
            415, "REMOTE_INVALID_MEDIA",
            "The downloaded bytes are not a recognized video container.",
            field, {"expectedType": kind},
        )
    if kind == "audio" and (
        not mime or not mime.startswith("audio/") and mime != "video/webm"
    ):
        raise SourceInputError(
            415, "REMOTE_INVALID_MEDIA",
            "The downloaded bytes are not a recognized audio format.",
            field, {"expectedType": kind},
        )


def validate_pdf(data: bytes, mime: str, field: str = "file") -> None:
    if mime == "application/pdf" and not is_pdf(data):
        raise SourceInputError(
            415,
            "INVALID_PDF",
            "The file declares PDF content but does not begin with PDF magic bytes.",
            field,
            {"mimeType": mime},
        )


def _parse_url(url: str) -> tuple[str, object, str, int]:
    value = str(url or "").strip()
    if not value:
        raise SourceInputError(400, "INVALID_URL", "A URL is required.", "url")
    if len(value) > 2048:
        raise SourceInputError(400, "INVALID_URL", "The URL exceeds the 2048-character limit.", "url")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise SourceInputError(400, "INVALID_URL", str(exc), "url") from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise SourceInputError(400, "INVALID_URL", "Only HTTP and HTTPS URLs are allowed.", "url")
    if parsed.username is not None or parsed.password is not None:
        raise SourceInputError(400, "URL_CREDENTIALS_NOT_ALLOWED", "URLs containing credentials are not allowed.", "url")
    if any(ord(char) <= 32 for char in value):
        raise SourceInputError(400, "INVALID_URL", "The URL contains whitespace or control characters.", "url")
    host = parsed.hostname
    if not host:
        raise SourceInputError(400, "INVALID_URL", "The URL must include a hostname.", "url")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SourceInputError(400, "INVALID_URL", "The URL hostname is invalid.", "url") from exc
    return value, parsed, host, port or (443 if parsed.scheme.lower() == "https" else 80)


def _resolved_addresses(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SourceInputError(
            400,
            "REMOTE_DNS_ERROR",
            "The URL hostname could not be resolved.",
            "url",
            {"reason": str(exc)},
        ) from exc
    addresses: list[str] = []
    for record in records:
        raw = str(record[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SourceInputError(400, "REMOTE_DNS_ERROR", "The URL resolved to an invalid IP address.", "url") from exc
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        blocked = (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )
        if blocked:
            raise SourceInputError(
                400,
                "BLOCKED_URL_ADDRESS",
                "URLs resolving to loopback, private, link-local, reserved, or multicast addresses are not allowed.",
                "url",
                {"hostname": host, "address": address.compressed},
            )
        if address.compressed not in addresses:
            addresses.append(address.compressed)
    if not addresses:
        raise SourceInputError(400, "REMOTE_DNS_ERROR", "The URL hostname resolved to no usable addresses.", "url")
    return addresses


def _pinned_url(parsed: object, address: str) -> str:
    literal = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
    authority = f"{literal}:{parsed.port}" if parsed.port else literal
    return urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, ""))


def _host_header(parsed: object, host: str) -> str:
    value = f"[{host}]" if ":" in host else host
    return f"{value}:{parsed.port}" if parsed.port else value


def _filename(remote_url: str, mime: str) -> str:
    name = unquote(urlsplit(remote_url).path).rsplit("/", 1)[-1].strip()
    if not name:
        name = "source"
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    extensions = config.MIME_EXTENSIONS.get(mime, [])
    if extensions and (not suffix or f".{suffix}" not in extensions):
        name += extensions[0]
    return name


def _content_length(response: object) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceInputError(
            502,
            "INVALID_CONTENT_LENGTH",
            "The remote server returned an invalid Content-Length header.",
            "url",
        ) from exc
    if length < 0:
        raise SourceInputError(502, "INVALID_CONTENT_LENGTH", "The remote server returned a negative Content-Length.", "url")
    return length


async def fetch_url(
    url: str,
    allowed_mimetypes: set[str] | list[str] | None = None,
    max_bytes: int = MAX_REMOTE_BYTES,
    expected_kind: str | None = None,
) -> RemoteSource:
    requested, _, _, _ = _parse_url(url)
    allowed = None if allowed_mimetypes is None else {_content_type(mime) for mime in allowed_mimetypes}
    current = requested
    redirects = 0
    while True:
        public_url, parsed, host, port = _parse_url(current)
        addresses = _resolved_addresses(host, port)
        connected = addresses[0]
        request_url = _pinned_url(parsed, connected)
        headers = {
            "Accept": (
                "image/*" if expected_kind == "image" else
                "video/*" if expected_kind == "video" else
                "audio/*" if expected_kind == "audio" else "*/*"
            ),
            "Host": _host_header(parsed, host),
            "User-Agent": REMOTE_USER_AGENT,
        }
        extensions = {"sni_hostname": host} if parsed.scheme.lower() == "https" else None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(REMOTE_TIMEOUT_SECONDS, connect=REMOTE_CONNECT_TIMEOUT_SECONDS),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET", request_url, headers=headers, extensions=extensions
                ) as response:
                    status = response.status_code
                    if 300 <= status < 400 and response.headers.get("location"):
                        if redirects >= MAX_REDIRECTS:
                            raise SourceInputError(
                                502,
                                "REMOTE_REDIRECT_ERROR",
                                f"The URL exceeded the {MAX_REDIRECTS}-redirect limit.",
                                "url",
                                {"maxRedirects": MAX_REDIRECTS},
                            )
                        current = urljoin(public_url, response.headers["location"])
                        redirects += 1
                        continue
                    if not response.is_success:
                        code = "REMOTE_ACCESS_DENIED" if status in (401, 403) else (
                            "REMOTE_HTTP_ERROR"
                        )
                        raise SourceInputError(
                            502,
                            code,
                            (
                                "The remote server denied Inquvia's fetch request; "
                                "the media itself could not be acquired."
                                if status in (401, 403)
                                else f"The remote server returned HTTP {status}."
                            ),
                            "url",
                            {"statusCode": status},
                        )
                    declared = _content_type(response.headers.get("content-type"))
                    length = _content_length(response)
                    if length is not None and length > max_bytes:
                        raise SourceInputError(
                            413,
                            "REMOTE_SIZE_LIMIT",
                            "The remote file exceeds the 10MB limit.",
                            "url",
                            {"maxSizeBytes": max_bytes, "receivedSizeBytes": length},
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise SourceInputError(
                                413,
                                "REMOTE_SIZE_LIMIT",
                                "The remote file exceeds the 10MB limit.",
                                "url",
                                {"maxSizeBytes": max_bytes},
                            )
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data:
                        raise SourceInputError(400, "REMOTE_EMPTY_RESPONSE", "The remote server returned an empty response.", "url")
                    final_url = public_url
                    mime = normalize_mime(data, declared, final_url)
                    if expected_kind == "audio" and mime == "video/webm":
                        mime = "audio/webm"
                    validate_pdf(data, mime)
                    if expected_kind:
                        validate_media_bytes(data, expected_kind)
                    if allowed is not None and mime not in allowed:
                        raise SourceInputError(
                            415,
                            "REMOTE_UNSUPPORTED_TYPE",
                            f"The URL resolved to {mime}, which is incompatible with this endpoint.",
                            "url",
                            {"receivedMimeType": mime, "acceptedMimeTypes": sorted(allowed)},
                        )
                    return RemoteSource(
                        data=data,
                        requested_url=requested,
                        final_url=final_url,
                        filename=_filename(final_url, mime),
                        mime_type=mime,
                        declared_mime=declared,
                        status_code=status,
                        redirects=redirects,
                        resolved_ips=addresses,
                        connected_ip=connected,
                        encoding=response.encoding,
                    )
        except SourceInputError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceInputError(504, "REMOTE_TIMEOUT", "The remote server timed out.", "url") from exc
        except httpx.HTTPError as exc:
            raise SourceInputError(502, "REMOTE_CONNECTION_ERROR", "The remote file could not be fetched.", "url") from exc


def _decode(source: RemoteSource) -> str:
    return source.data.decode(source.encoding or "utf-8", errors="replace")


def _empty_inspection(source: RemoteSource) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "url": source.requested_url,
        "finalUrl": source.final_url,
        "hostname": urlsplit(source.final_url).hostname or "",
        "dnsRecords": source.resolved_ips,
        "sslValid": None,
        "sslIssuer": None,
        "sslDaysRemaining": None,
        "statusCode": source.status_code,
        "isOnline": True,
        "access": {"limited": False, "reason": None, "blocked": False, "statusCode": source.status_code},
        "redirects": source.redirects,
        "httpError": None,
        "retrievalTimestamp": now,
        "title": None,
        "metaDescription": None,
        "bodySnippet": None,
        "content": None,
        "fullText": None,
        "chunks": [],
        "chunkCount": 0,
        "totalTextLength": 0,
        "renderMode": "static",
        "jsDetected": False,
        "renderNote": None,
        "headings": [],
        "paragraphs": [],
        "lists": [],
        "tables": [],
        "metadata": {},
        "links": [],
        "headingCount": 0,
        "paragraphCount": 0,
        "listCount": 0,
        "tableCount": 0,
        "linkCount": 0,
        "extractionFull": False,
        "extractionLimited": False,
        "sourceUrl": source.final_url,
        "contentQuality": {
            "completeness": "empty",
            "issues": ["No readable text content extracted"],
            "metrics": {},
            "signals": {},
        },
        "extractionTimestamp": now,
        "documentExtraction": None,
    }


def inspect_source(source: RemoteSource) -> dict:
    inspection = _empty_inspection(source)
    if source.mime_type == "application/pdf":
        extracted = document_extract.extract_document_pages(source.data, source.mime_type)
        pages = (extracted or {}).get("pages") or []
        text = "\n\n".join(str(page.get("text") or "") for page in pages).strip()
        inspection.update({
            "content": text or None,
            "fullText": text or None,
            "bodySnippet": text[:1000] or None,
            "chunks": [text] if text else [],
            "chunkCount": 1 if text else 0,
            "totalTextLength": len(text),
            "extractionFull": True,
            "documentExtraction": extracted,
        })
        if extracted:
            inspection["contentQuality"] = {
                "completeness": extracted.get("extractionQuality") or "empty",
                "issues": [],
                "metrics": extracted.get("qualityMetrics") or {},
                "signals": {},
            }
        return inspection
    if source.mime_type in HTML_MIMES:
        html = _decode(source)
        extracted = web_inspector._extraction_result(source.final_url, html)
        inspection.update(extracted)
        return inspection
    if source.mime_type.startswith("text/") or source.mime_type in (
        "application/json", "application/x-jsonlines", "application/xml", "text/xml",
    ):
        text = _decode(source).strip()
        inspection.update({
            "content": text or None,
            "fullText": text or None,
            "bodySnippet": text[:1000] or None,
            "chunks": web_inspector._chunk_content(text),
            "chunkCount": len(web_inspector._chunk_content(text)),
            "totalTextLength": len(text),
            "extractionFull": True,
            "contentQuality": {
                "completeness": "complete" if text else "empty",
                "issues": [] if text else ["No text content extracted"],
                "metrics": {"text_length": len(text)},
                "signals": {"suspiciously_short": not text},
            },
        })
    return inspection


def evidence_items(
    data: bytes,
    mime: str,
    filename: str = "",
    source_url: str = "",
    inspection: dict | None = None,
) -> list[dict]:
    source = source_url or filename or "uploaded source"
    provenance = {
        "sourceType": "url" if source_url else "upload",
        "source": source,
        "sourceUrl": source_url or None,
        "filename": filename or None,
        "mimeType": mime,
    }
    if mime == "application/pdf":
        extracted = (inspection or {}).get("documentExtraction") or document_extract.extract_document_pages(data, mime)
        pages = (extracted or {}).get("pages") or []
        if not pages:
            return [{
                "type": "document",
                "status": "extracted",
                "text": f"PDF retrieved from {source}, but no readable pages were extracted.",
                "finding": f"PDF retrieved from {source}, but no readable pages were extracted.",
                "sources": [source],
                "provenance": provenance,
                "metadata": {"source": source, "sourceUrl": source_url or None, "filename": filename or None, "mimeType": mime, "evidenceUnavailable": True},
            }]
        result = []
        for page in pages:
            page_number = page.get("page")
            text = str(page.get("text") or "").strip() or f"Page {page_number}: no readable text was extracted."
            result.append({
                "type": "document",
                "status": "extracted",
                "text": text,
                "finding": text,
                "sources": [source],
                "provenance": provenance,
                "metadata": {
                    "source": source,
                    "sourceUrl": source_url or None,
                    "filename": filename or None,
                    "mimeType": mime,
                    "page": page_number,
                    "pageCount": extracted.get("pageCount"),
                    "extractionSource": page.get("source"),
                    "tableCount": len(page.get("tables") or []),
                },
            })
        return result
    inspected = inspection
    if inspected is None:
        synthetic = RemoteSource(
            data=data,
            requested_url=source_url,
            final_url=source_url,
            filename=filename,
            mime_type=mime,
            declared_mime=mime,
            status_code=200,
            redirects=0,
            resolved_ips=[],
            connected_ip="",
        )
        inspected = inspect_source(synthetic)
    text = str(inspected.get("fullText") or inspected.get("content") or "").strip()
    if not text:
        text = str(inspected.get("bodySnippet") or "").strip() or f"No readable text was extracted from {source}."
    return [{
        "type": "url" if source_url else "text",
        "status": "extracted",
        "text": text,
        "finding": text,
        "sources": [source],
        "provenance": provenance,
        "metadata": {
            "source": source,
            "sourceUrl": source_url or None,
            "filename": filename or None,
            "mimeType": mime,
            "page": 1,
            "pageCount": 1,
            "title": inspected.get("title"),
            "extractionSource": inspected.get("renderMode") or "text",
        },
    }]


def store_remote_input(
    source: RemoteSource,
    case_id: str,
    capability_id: str | None = None,
    input_type: str | None = None,
    reused_from: str | None = None,
    inspection: dict | None = None,
) -> dict:
    stored = storage.store_file(source.data, source.filename, source.mime_type, case_id)
    resolved_type = input_type or config.mime_input_type(source.mime_type, capability_id)
    result = {
        "type": resolved_type,
        "content": source.requested_url if resolved_type == "url" else source.filename,
        "fileName": stored["fileName"],
        "mimeType": stored["mimeType"],
        "filePath": stored["filePath"],
        "size": stored["size"],
        "sourceUrl": source.requested_url,
        "finalUrl": source.final_url,
    }
    if inspection is not None:
        result["inspection"] = inspection
    if reused_from:
        result["reusedFrom"] = reused_from
    return result
