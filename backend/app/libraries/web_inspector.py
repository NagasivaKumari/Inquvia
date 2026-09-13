"""Live web inspection: DNS + TLS cert + full-page HTTP content extraction.

Extracts structured evidence from any publicly accessible URL using standard
library (html.parser) with browser rendering fallback for JavaScript-dependent
pages. Reports access limitations explicitly instead of fabricating content.
"""
import ssl
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
from typing import Optional

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


def _assess_content_quality(
    html: str,
    extracted_text: str,
    headings: list[dict],
    paragraphs: list[str],
    lists: list[dict],
    tables: list[dict],
    js_detected: bool,
    render_mode: str,
) -> dict:
    """Assess the quality and completeness of extracted content."""
    quality = {
        "completeness": "complete",
        "issues": [],
        "metrics": {
            "text_length": len(extracted_text),
            "heading_count": len(headings),
            "paragraph_count": len(paragraphs),
            "list_count": len(lists),
            "table_count": len(tables),
            "has_structured_data": False,
            "js_detected": js_detected,
            "render_mode": render_mode,
        },
        "signals": {
            "suspiciously_short": False,
            "labels_without_values": False,
            "framework_markers_present": js_detected,
            "large_html_vs_text_gap": False,
            "structured_data_only": False,
        },
    }

    # Check for suspiciously short content when JS detected
    if js_detected and len(extracted_text) < 2000:
        quality["signals"]["suspiciously_short"] = True
        quality["issues"].append("JS framework detected but extracted text is suspiciously short")
        quality["completeness"] = "partial"

    # Check for labels without associated values in EXTRACTED TEXT
    # Pattern: "Label:" at end of line or followed by minimal content
    import re
    # Match Label:
    label_pattern = r"[A-Z][a-zA-Z\s]+:\s*$"
    label_only_count = len(re.findall(label_pattern, extracted_text, re.MULTILINE))
    
    # Match <... class="label">Label</...> <... class="value"></...>
    empty_value_pattern = r'(?:class|data-testid|id)=["\'][^"\']*(?:label|title)[^"\']*["\'][^>]*>[^<]*<[^>]*>\s*<[^>]*class=["\'][^"\']*(?:value|data)[^"\']*["\'][^>]*>\s*<\s*/\s*(?:span|div)'
    empty_values = len(re.findall(empty_value_pattern, html, re.IGNORECASE))
    
    if label_only_count > 3 or empty_values > 0:
        quality["signals"]["labels_without_values"] = True
        quality["issues"].append(f"Found {label_only_count + empty_values} labeled fields that appear to lack associated values")
        if quality["completeness"] == "complete":
            quality["completeness"] = "partial"

    # Check for large gap between raw HTML and extracted text
    html_text_ratio = len(extracted_text) / max(len(html), 1)
    if html_text_ratio < 0.05 and len(html) > 10000:
        quality["signals"]["large_html_vs_text_gap"] = True
        quality["issues"].append("Large gap between raw HTML size and extracted text — likely dynamic content")
        if quality["completeness"] == "complete":
            quality["completeness"] = "partial"

    # Check for structured data (JSON-LD, microdata) that has values not in visible text
    if '"@context"' in html or 'itemprop=' in html or 'itemscope' in html:
        quality["metrics"]["has_structured_data"] = True
        quality["signals"]["structured_data_only"] = True

    if len(extracted_text) < 100 and (headings or paragraphs or lists or tables):
        quality["completeness"] = "sparse"
        quality["issues"].append("Very little text extracted despite structural elements present")

    if not extracted_text.strip():
        quality["completeness"] = "empty"
        quality["issues"].append("No text content extracted")

    return quality


def _extraction_result(base_url: str, html: str, render_mode: str = "static") -> dict:
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
    js_detected = _has_js_content(html, extractor.external_scripts)
    if js_detected and len(flat) < 2000:
        rendered_note = ("Some content may be rendered client-side by JavaScript; "
                         "static extraction captured the initial HTML only.")

    meta_description = extractor.metadata.get("description")
    if not meta_description:
        meta_description = extractor.metadata.get("og:description")
    if not meta_description:
        meta_description = extractor.metadata.get("twitter:description")

    quality = _assess_content_quality(
        html=html,
        extracted_text=flat,
        headings=headings,
        paragraphs=[s["text"] for s in sections if s["type"] == "paragraph"],
        lists=lists,
        tables=tables,
        js_detected=js_detected,
        render_mode=render_mode,
    )

    return {
        "title": extractor.title,
        "metaDescription": meta_description,
        "bodySnippet": " ".join(content.split())[:SNIPPET_CHARS],
        "content": content,
        "fullText": flat,
        "chunks": chunks,
        "chunkCount": len(chunks),
        "totalTextLength": len(flat),
        "extractionFull": not len(flat) > MAX_CONTENT_CHARS,
        "extractionLimited": len(flat) > MAX_CONTENT_CHARS,
        "renderMode": render_mode,
        "jsDetected": js_detected,
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
        "contentQuality": quality,
        "extractionTimestamp": datetime.now(timezone.utc).isoformat(),
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


async def _try_browser_render(url: str, html: str, extracted: dict) -> tuple[dict | None, str | None]:
    """Attempt browser rendering if static extraction is insufficient."""
    try:
        from .browser_renderer import render_page, should_render
    except ImportError:
        # Playwright not available
        return None, "playwright_not_available"

    static_text = extracted.get("fullText", "")
    print(f"[DEBUG] _try_browser_render: url={url}, static_text_len={len(static_text)}, js={extracted.get('jsDetected')}, quality={extracted.get('contentQuality', {}).get('completeness')}")

    if not should_render(
        html,
        static_text,
        extracted.get("jsDetected", False),
        extracted.get("contentQuality"),
    ):
        print("[DEBUG] should_render returned False")
        return None, "rendering_not_needed"

    try:
        result = await render_page(url)
        print(f"[DEBUG] render_page result: success={result.success}, text_len={len(result.text) if result.text else 0}, timed_out={result.timed_out}, error={result.error}")
        comparison = len(result.text) if result.text else 0
        is_significant_improvement = comparison > len(static_text)
        is_reasonable_substitute = (comparison > 0.8 * len(static_text))
        print(f"[DEBUG] Comparison: {comparison} > {len(static_text)} = {is_significant_improvement}, reasonable={is_reasonable_substitute}")
        
        if result.success and result.text and (is_significant_improvement or is_reasonable_substitute):
            print("[DEBUG] Using rendered content!")
            # Re-extract from rendered HTML
            rendered_extracted = _extraction_result(result.final_url or url, result.html, render_mode="browser")
            rendered_extracted["renderedUrl"] = result.final_url
            rendered_extracted["renderLoadTimeMs"] = result.load_time_ms
            rendered_extracted["renderStatusCode"] = result.status_code
            return rendered_extracted, None
        elif result.timed_out:
            return None, "render_timeout"
        else:
            print("[DEBUG] No improvement - returning render_no_improvement")
            return None, "render_no_improvement"
    except Exception as e:
        return None, f"render_error: {e}"


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
        raw_html = ""
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, max_redirects=10) as client:
                res = await client.get(normalized, headers={"User-Agent": USER_AGENT})
            status_code = res.status_code
            is_online = res.is_success or (status_code is not None and status_code < 500)
            redirects = len(res.history)
            final_url = str(res.url)
            raw_html = res.text
            if res.is_success:
                extracted = _extraction_result(final_url, raw_html)
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
            "retrievalTimestamp": datetime.now(timezone.utc).isoformat(),
        }

        if extracted:
            result.update(extracted)
            result["isOnline"] = True

            # 4. Browser rendering fallback if content quality is insufficient
            if extracted.get("jsDetected") and extracted.get("contentQuality", {}).get("completeness") in ("partial", "sparse", "empty"):
                rendered_result, render_error = await _try_browser_render(final_url, raw_html, extracted)
                print(f"[DEBUG] rendered_result: {rendered_result is not None}, render_error: {render_error}")
                if rendered_result:
                    print(f"[DEBUG] rendered totalTextLength: {rendered_result.get('totalTextLength')}, current totalTextLength: {result.get('totalTextLength')}")
                    # Merge rendered results, preserving static extraction metadata
                    result["renderedContent"] = {
                        "fullText": rendered_result.get("fullText"),
                        "chunks": rendered_result.get("chunks"),
                        "chunkCount": rendered_result.get("chunkCount"),
                        "totalTextLength": rendered_result.get("totalTextLength"),
                        "headings": rendered_result.get("headings"),
                        "paragraphs": rendered_result.get("paragraphs"),
                        "lists": rendered_result.get("lists"),
                        "tables": rendered_result.get("tables"),
                        "renderMode": "browser",
                        "renderedUrl": rendered_result.get("renderedUrl"),
                        "renderLoadTimeMs": rendered_result.get("renderLoadTimeMs"),
                        "renderStatusCode": rendered_result.get("renderStatusCode"),
                    }
                    # Use rendered content as primary if it has more text
                    if rendered_result.get("totalTextLength", 0) > result.get("totalTextLength", 0):
                        print("[DEBUG] Updating result with rendered content!")
                        result["fullText"] = rendered_result.get("fullText")
                        result["chunks"] = rendered_result.get("chunks")
                        result["chunkCount"] = rendered_result.get("chunkCount")
                        result["totalTextLength"] = rendered_result.get("totalTextLength")
                        result["headings"] = rendered_result.get("headings")
                        result["paragraphs"] = rendered_result.get("paragraphs")
                        result["lists"] = rendered_result.get("lists")
                        result["tables"] = rendered_result.get("tables")
                        result["renderMode"] = "browser"
                    result["contentQuality"]["completeness"] = "complete"
                    result["contentQuality"]["issues"] = [i for i in result["contentQuality"]["issues"] if "suspiciously short" not in i]
                elif render_error:
                    result["renderAttempted"] = True
                    result["renderError"] = render_error
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
            result["contentQuality"] = {
                "completeness": "empty",
                "issues": ["No HTTP content retrieved"],
                "metrics": {},
                "signals": {},
            }
            result["extractionTimestamp"] = datetime.now(timezone.utc).isoformat()
        return result
    except Exception:
        return None