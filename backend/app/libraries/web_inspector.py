"""Live web inspection: DNS + TLS cert + full-page HTTP content extraction.

Extracts structured evidence from any publicly accessible URL using only the
standard library (html.parser) — no website-specific selectors — and reports
access limitations explicitly instead of fabricating content.
"""
import ssl
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

import httpx

# Maximum extracted text (chars) captured before we refuse to keep reading.
MAX_CONTENT_CHARS = 500_000
# Target size of each bounded content chunk.
CHUNK_SIZE = 8_000
# Backward-compatible short snippet length.
SNIPPET_CHARS = 1_000
# Max links captured per page (bounded provenance, not content).
MAX_LINKS = 500
# User agent advertised to servers (no anti-bot bypass attempted).
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InquviaForensics/2.0"


def _get_certificate(hostname: str, port: int = 443) -> dict | None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((hostname, port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname=hostname) as ssock:
                der = ssock.getpeercert(binary_form=True)
                if not der:
                    return None
                from cryptography import x509
                cert = x509.load_der_x509_certificate(der)
                subject = cert.subject
                issuer = cert.issuer
                org = None
                for attr in subject:
                    if attr.oid._name == "organizationName":
                        org = attr.value
                        break
                issuer_names = {a.oid._name: a.value for a in issuer}
                issuer_org = issuer_names.get("organizationName") or issuer_names.get("commonName")
                valid_to = cert.not_valid_after_utc
                return {
                    "issuer": issuer_org or "Trusted Authority",
                    "valid_to": valid_to.isoformat(),
                    "days_remaining": max(0, round((valid_to - datetime.now(timezone.utc)).total_seconds() / 86400)),
                }
    except Exception:
        return None


class _PageExtractor(HTMLParser):
    """Structural reader: captures title, headings, paragraphs, lists, tables,
    meta tags and links via standard HTML parsing, agnostic to any specific site."""

    _BLOCK_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"})

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title: str | None = None
        self.sections: list[dict] = []
        self.metadata: dict[str, str] = {}
        self.links: list[dict] = []
        self.external_scripts: int = 0
        self._buf: list[str] = []
        self._in_block: str | None = None
        self._heading_level: int = 0
        self._skip_depth: int = 0
        self._table_rows: list[list[str]] | None = None
        self._row_cells: list[str] | None = None
        self._list_items: list[str] | None = None
        self._list_ordered: bool = False
        self._list_stack: list[tuple[list[str], bool]] = []
        self._link_href: str | None = None
        self._link_text: list[str] | None = None

    # ---- block flushing ----------------------------------------------------
    def _flush_block(self) -> None:
        if self._in_block is None:
            return
        text = " ".join(self._buf).strip()
        text = " ".join(text.split())
        self._buf = []
        block = self._in_block
        self._in_block = None

        if block == "title":
            if text and not self.title:
                self.title = text
        elif block.startswith("h"):
            if text:
                self.sections.append({"type": "heading", "level": self._heading_level, "text": text})
        elif block == "p":
            if text:
                self.sections.append({"type": "paragraph", "text": text})
        elif block == "li":
            if text and self._list_items is not None:
                self._list_items.append(text)
        elif block == "cell":
            if text and self._row_cells is not None:
                self._row_cells.append(text)

    def _flush_row(self) -> None:
        if self._row_cells is not None and self._table_rows is not None:
            cells = [c for c in self._row_cells if c]
            if cells:
                self._table_rows.append(cells)
        self._row_cells = None

    def _flush_list(self) -> None:
        if self._list_items is not None:
            items = [i for i in self._list_items if i]
            if items:
                self.sections.append({"type": "list", "ordered": self._list_ordered, "items": items})
        if self._list_stack:
            self._list_stack.pop()
        self._list_items = self._list_stack[-1][0] if self._list_stack else None
        self._list_ordered = self._list_stack[-1][1] if self._list_stack else False

    # ---- parser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)

        if tag == "script":
            if attrs_dict.get("src"):
                self.external_scripts += 1
            self._skip_depth += 1
            return
        if tag == "style":
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if tag == "meta":
            key = attrs_dict.get("name") or attrs_dict.get("property")
            content = attrs_dict.get("content")
            if key and content and key not in self.metadata:
                self.metadata[key] = content
            return
        if tag == "a":
            self._link_href = attrs_dict.get("href") or ""
            self._link_text = []
            return
        if tag == "br":
            if self._in_block is not None:
                self._buf.append(" ")
            return
        if tag == "img":
            alt = (attrs_dict.get("alt") or "").strip()
            if alt and self._in_block is not None:
                self._buf.append(alt)
            return

        if tag in self._BLOCK_TAGS or tag in ("table", "tr", "ul", "ol"):
            self._flush_block()

        if tag == "title":
            self._in_block = "title"
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_block = tag
            self._heading_level = int(tag[1])
        elif tag == "p":
            self._in_block = "p"
        elif tag == "li":
            self._in_block = "li"
        elif tag in ("td", "th"):
            self._in_block = "cell"
            if self._row_cells is None:
                self._row_cells = []
        elif tag == "table":
            self._table_rows = []
        elif tag == "tr":
            self._row_cells = []
        elif tag in ("ul", "ol"):
            self._list_items = []
            self._list_ordered = tag == "ol"
            self._list_stack.append((self._list_items, self._list_ordered))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return

        if tag == "a":
            href = self._link_href
            text = " ".join(self._link_text or []).strip()
            if href and text and len(self.links) < MAX_LINKS:
                if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    full = href
                else:
                    full = urljoin(self.base_url, href)
                self.links.append({"href": full, "text": text[:500]})
            self._link_href = None
            self._link_text = None
            return

        if tag == "title":
            self._flush_block()
        elif tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self._flush_block()
        elif tag == "p":
            self._flush_block()
        elif tag == "li":
            self._flush_block()
        elif tag in ("td", "th"):
            self._flush_block()
        elif tag == "tr":
            self._flush_block()
            self._flush_row()
        elif tag == "table":
            self._flush_block()
            self._flush_row()
            if self._table_rows:
                self.sections.append({"type": "table", "rows": self._table_rows})
            self._table_rows = None
        elif tag in ("ul", "ol"):
            self._flush_block()
            self._flush_list()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._link_text is not None:
            self._link_text.append(text)
        elif self._in_block is not None:
            self._buf.append(text)


def _format_sections(sections: list[dict]) -> str:
    """Render parsed sections into readable text with structural markers."""
    lines: list[str] = []
    for sec in sections:
        if sec["type"] == "heading":
            lines.append(f"\n{'#' * sec['level']} {sec['text']}")
        elif sec["type"] == "paragraph":
            lines.append(sec["text"])
        elif sec["type"] == "list":
            for item in sec["items"]:
                lines.append(f"- {item}")
        elif sec["type"] == "table":
            lines.append("\n[TABLE]")
            for row in sec["rows"]:
                lines.append(" | ".join(cell for cell in row))
            lines.append("[/TABLE]")
    return "\n".join(lines)


# Generic client-side framework markers — never a site-specific selector.
_JS_RENDER_MARKERS = (
    "__NEXT_DATA__",
    "window.__NUXT__",
    "window.__NUXT",
    "__APP__",
    "data-reactroot",
    "ng-version=",
    'id="root"', 'id="app"',
    "id='root'", "id='app'",
)


def _has_js_content(html: str, external_scripts: int) -> bool:
    return external_scripts > 0 or any(m in html for m in _JS_RENDER_MARKERS)


def _chunk_content(text: str, *, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split a long text into labeled bounded chunks (never silently drop)."""
    if len(text) <= chunk_size:
        return [text] if text else []
    count = (len(text) - 1) // chunk_size + 1
    return [f"[chunk {i + 1} of {count}] {text[i:i + chunk_size]}"
            for i in range(0, len(text), chunk_size) if text[i:i + chunk_size]]


def _extraction_result(base_url: str, html: str) -> dict:
    extractor = _PageExtractor(base_url)
    try:
        extractor.feed(html)
    except Exception:
        pass  # partial parse is better than none; caller never fabricates
    extractor.close()
    extractor._flush_block()
    extractor._flush_row()
    extractor._flush_list()

    sections = extractor.sections
    flat = " ".join(_format_sections(sections).split())
    if len(flat) > MAX_CONTENT_CHARS:
        flat = flat[:MAX_CONTENT_CHARS]
    chunks = _chunk_content(flat)
    content = chunks[0] if chunks else ""

    headings = [{"level": s["level"], "text": s["text"]} for s in sections if s["type"] == "heading"]
    lists = [{"ordered": s.get("ordered", False), "items": s["items"]} for s in sections if s["type"] == "list"]
    tables = [{"rows": s["rows"]} for s in sections if s["type"] == "table"]
    rendered_note = None
    if _has_js_content(html, extractor.external_scripts) and len(flat) < 2000:
        rendered_note = ("Some content may be rendered client-side by JavaScript; "
                         "static extraction captured the initial HTML only.")

    meta_description = extractor.metadata.get("description")
    if not meta_description:
        meta_description = extractor.metadata.get("og:description")
    if not meta_description:
        meta_description = extractor.metadata.get("twitter:description")

    return {
        "title": extractor.title,
        "metaDescription": meta_description,
        "bodySnippet": " ".join(content.split())[:SNIPPET_CHARS],
        "content": content,          # first bounded chunk — safe default for AI
        "fullText": flat,            # complete bounded page text — never truncated
        "chunks": chunks,
        "chunkCount": len(chunks),
        "totalTextLength": len(flat),
        "extractionFull": not len(flat) > MAX_CONTENT_CHARS,
        "extractionLimited": len(flat) > MAX_CONTENT_CHARS,
        "renderMode": "static",
        "jsDetected": _has_js_content(html, extractor.external_scripts),
        "renderNote": rendered_note,
        "headings": headings,
        "paragraphs": [s["text"] for s in sections if s["type"] == "paragraph"],
        "lists": lists,
        "tables": tables,
        "metadata": extractor.metadata,
        "links": extractor.links,
"headingCount": len(headings),
    "paragraphCount": len([s for s in sections if s["type"] == "paragraph"]),
    "listCount": len(lists),
        "tableCount": len(tables),
        "linkCount": len(extractor.links),
        "sourceUrl": extractor.base_url,
    }


def _access_blocked(status_code: int | None, error: str | None, *, redirects: int = 0) -> dict:
    if error:
        return {"limited": True, "reason": error, "statusCode": status_code, "blocked": True,
                "redirects": redirects}
    if status_code is None:
        return {"limited": True, "reason": "No HTTP response received.", "statusCode": None,
                "blocked": True, "redirects": redirects}
    code_map = {
        401: "HTTP 401 — endpoint requires authentication",
        403: "HTTP 403 — access forbidden by the server",
        404: "HTTP 404 — page not found",
        408: "HTTP 408 — request timeout",
        410: "HTTP 410 — resource permanently removed",
        429: "HTTP 429 — rate limited by the server",
        500: "HTTP 500 — internal server error",
        502: "HTTP 502 — bad gateway",
        503: "HTTP 503 — service unavailable",
        504: "HTTP 504 — gateway timeout",
    }
    if 400 <= status_code < 500:
        reason = code_map.get(status_code, f"HTTP {status_code} — client error")
    elif 500 <= status_code < 600:
        reason = code_map.get(status_code, f"HTTP {status_code} — server error")
    else:
        reason = f"HTTP {status_code}"
    return {"limited": True, "reason": reason, "statusCode": status_code, "blocked": True,
            "redirects": redirects}


async def inspect_live_url(target_url: str) -> dict | None:
    try:
        normalized = target_url.strip()
        if not normalized.startswith("http://") and not normalized.startswith("https://"):
            normalized = "https://" + normalized
        parsed = urlparse(normalized)
        hostname = parsed.hostname or ""

        # 1. DNS resolution (A records).
        dns_records: list[str] = []
        try:
            import socket as _socket
            records = _socket.getaddrinfo(hostname, None, _socket.AF_INET)
            dns_records = [item[4][0] for item in records if item[4] and item[4][0]]
            dns_records = list(dict.fromkeys(dns_records))
        except Exception:
            dns_records = []

        # 2. SSL inspection.
        ssl_valid = False
        ssl_issuer = None
        ssl_days_remaining = None
        if parsed.scheme == "https":
            cert = _get_certificate(hostname, parsed.port or 443)
            if cert:
                ssl_valid = True
                ssl_issuer = cert["issuer"]
                ssl_days_remaining = cert["days_remaining"]

        # 3. Live HTTP page fetch.
        status_code = None
        is_online = False
        access: dict = {"limited": False, "reason": None, "blocked": False, "statusCode": None}
        extracted: dict | None = None
        http_error: str | None = None
        final_url = normalized
        redirects = 0
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True, max_redirects=10) as client:
                res = client.get(normalized, headers={"User-Agent": USER_AGENT})
            status_code = res.status_code
            is_online = res.is_success or (status_code is not None and status_code < 500)
            redirects = len(res.history)
            final_url = str(res.url)
            if res.is_success:
                extracted = _extraction_result(final_url, res.text)
            else:
                access = _access_blocked(status_code, None, redirects=redirects)
        except httpx.TimeoutException:
            http_error = "Connection timed out while fetching the page."
            access = _access_blocked(None, http_error)
        except httpx.ConnectError:
            http_error = "Could not connect to the server."
            access = _access_blocked(None, http_error)
        except Exception:
            http_error = "Network failure while fetching the page."
            access = _access_blocked(None, http_error)

        result: dict = {
            "url": normalized,
            "finalUrl": final_url,
            "hostname": hostname,
            "dnsRecords": dns_records,
            "sslValid": ssl_valid,
            "sslIssuer": ssl_issuer,
            "sslDaysRemaining": ssl_days_remaining,
            "statusCode": status_code,
            "isOnline": is_online,
            "access": access,
            "redirects": redirects,
            "httpError": http_error,
        }

        if extracted:
            result.update(extracted)
            result["isOnline"] = True
        else:
            result["bodySnippet"] = None
            result["content"] = None
            result["fullText"] = None
            result["chunks"] = []
            result["chunkCount"] = 0
            result["headings"] = []
            result["paragraphs"] = []
            result["lists"] = []
            result["tables"] = []
            result["metadata"] = {}
            result["links"] = []
            result["totalTextLength"] = 0
            result["renderMode"] = "static"
            result["jsDetected"] = False
            result["headingCount"] = 0
            result["paragraphCount"] = 0
            result["listCount"] = 0
            result["tableCount"] = 0
            result["linkCount"] = 0
            result["extractionFull"] = False
            result["extractionLimited"] = False
            result["sourceUrl"] = None
        return result
    except Exception:
        return None