"""Page-structured document extraction (PDF text layer / plain text).

Extraction is comprehensive and question-agnostic by design: every page is
retained with its page number and a label describing where its text came from
— a selectable text layer ("text_layer"), rendered page ("visual"),
or OCR-derived ("ocr" / "visual_ocr"). Choosing which pages or passages are
relevant to the user's question happens LATER, in analysis; nothing in this
module reads the question.

When normal text extraction fails, is empty, incomplete, or corrupted, the
module detects the failure (extraction quality is measured, not just
"text exists / no text") and automatically attempts fallback extraction:
rendering PDF pages to images and extracting text visually (OCR via the
app's multimodal capability). Rendered-page evidence is combined with the
text layer when possible, so a broken text layer does not automatically
become "evidence unavailable".

Structured layouts (section tables) are preserved: PDF tables are detected
with PyMuPDF's table finder and kept as rows/columns tagged with their page
and in-page position, so topic groupings and section relationships survive
extraction instead of being flattened.

PDFs are read with PyMuPDF (fitz) when installed. When no extractor is
installed or a document genuinely contains no readable content after all
fallback attempts, extraction returns pages labeled as unread (empty text,
source 'ocr'/'visual') — never fabricated text. It returns None only when
the document itself cannot be read at all (evidence unavailable).
"""
import base64
import io
import re

try:
    from .evidence_types import ExtractionQuality, EvidenceResult
except ImportError:  # run directly as a script (module __main__ self-check)
    from evidence_types import ExtractionQuality, EvidenceResult

MAX_PAGES = 200
MIN_EXTRACTION_QUALITY = 50
EXTRACTION_QUALITY_THRESHOLD = 0.3
# A page whose recovered text is shorter than this is treated as suspicious
# (likely missing its real content) and eligible for visual/OCR recovery.
SHORT_PAGE_CHARS = 40
# A whole-document text shorter than this is treated as suspiciously short.
MIN_DOCUMENT_CHARS = 100
# Share of replacement/control characters that flags a page as corrupted.
CORRUPT_CHAR_RATIO = 0.05


def _safe_text(raw: str) -> str:
    return re.sub(r"\r\n?", "\n", raw or "").strip()


def _corrupted_char_count(text: str) -> int:
    """Characters that indicate a broken/corrupted extraction: U+FFFD
    replacement chars and stray control chars (newlines/tabs are fine)."""
    if not text:
        return 0
    sense = text.replace("\n", "").replace("\t", "").replace("\r", "")
    return sum(
        1 for ch in sense
        if ch == "\ufffd" or (ord(ch) < 32) or (0x7F <= ord(ch) <= 0x9F)
    )


def _is_corrupted(text: str) -> bool:
    sense_len = len(text.replace("\n", "").replace("\t", "").replace("\r", "").strip())
    if sense_len == 0:
        return False
    return (_corrupted_char_count(text) / sense_len) >= CORRUPT_CHAR_RATIO


def _table_like_lines(text: str) -> int:
    """Lines that look like flattened table rows (multiple column separators).
    Used as a hint that a text layer may have lost its table structure."""
    if not text:
        return 0
    count = 0
    for line in text.splitlines():
        if line.count("|") >= 2 or "\t" in line:
            count += 1
    return count


def _assess_extraction_quality(pages: list[dict]) -> dict:
    """Measure extraction quality across the whole document.

    Detects, generically:
      - empty extraction            (no page has text)
      - suspiciously short text     (very little extracted per page / in total)
      - corrupted text              (replacement/stray control characters)
      - missing large portions      (low page coverage / empty pages)
      - table extraction failure    (table-like lines but no table structure)
      - scanned/image-only pages    (pages with no text at all)

    Returns {quality, metrics, ...} where quality is one of
    'complete' | 'partial' | 'sparse' | 'empty' and metrics carries the
    per-page/summary numbers used to detect the above.
    """
    if not pages:
        return {
            "method": "direct",
            "success": False,
            "features_detected": [],
            "page_range": None,
            "quality": "empty",
            "metrics": {"pages_total": 0, "pages_with_text": 0, "coverage": 0.0,
                        "total_chars": 0, "corrupted_chars": 0, "tables_detected": 0},
        }

    pages_with_text = sum(1 for p in pages if (p.get("text") or "").strip())
    total_pages = len(pages)
    coverage = pages_with_text / total_pages

    lengths = [len((p.get("text") or "").strip()) for p in pages]
    total_chars = sum(lengths)
    avg_chars = total_chars / total_pages if total_pages else 0
    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0

    corrupted = sum(_corrupted_char_count(p.get("text") or "") for p in pages)
    tables_detected = 0
    table_pages = 0
    for p in pages:
        ts = p.get("tables") or []
        if ts:
            tables_detected += len(ts)
            table_pages += 1

    features = []
    if pages_with_text:
        features.append("text")
    if tables_detected:
        features.append("tables")
    if any(p.get("image") for p in pages):
        features.append("images")
    if any(p.get("source") in ("ocr", "visual", "visual_ocr") for p in pages):
        features.append("scanned_pages")
    # table-like content exists in the text layer but no table structure was
    # recovered → possible table extraction failure.
    table_like_pages = sum(1 for p in pages if _table_like_lines(p.get("text") or "") >= 2)

    metric = {
        "pages_total": total_pages,
        "pages_with_text": pages_with_text,
        "coverage": round(coverage, 3),
        "total_chars": total_chars,
        "avg_chars_per_page": round(avg_chars, 1),
        "min_text_length": min_len,
        "max_text_length": max_len,
        "corrupted_chars": corrupted,
        "tables_detected": tables_detected,
        "table_pages": table_pages,
        "table_like_lines_without_structure": table_like_pages,
        "suspicious_pages": [
            i + 1 for i, p in enumerate(pages)
            if not (p.get("text") or "").strip() or _is_corrupted(p.get("text") or "")
        ],
    }

    plain_only = all(p.get("source") == "plain_text" for p in pages)
    if pages_with_text == 0:
        quality = "empty"
    elif plain_only:
        # A plain-text document IS its own bytes — nothing was "extracted" and
        # nothing can be missing, so any content is a complete extraction.
        quality = "complete"
    elif (
        (total_pages >= 2 and total_chars < MIN_DOCUMENT_CHARS)
        or avg_chars < SHORT_PAGE_CHARS
    ):
        quality = "sparse"
    elif coverage < 1.0:
        quality = "partial"
    elif corrupted > 0 or table_like_pages > 0 and tables_detected == 0:
        # Text covers all pages, but some is corrupted or a table structure was
        # lost → the extraction is usable but not trustworthy on its own.
        quality = "partial"
    else:
        quality = "complete"

    return {
        "method": "direct",
        "success": pages_with_text > 0,
        "features_detected": features,
        "page_range": [1, total_pages] if total_pages > 0 else None,
        "quality": quality,
        "metrics": metric,
    }


def _extract_tables(page, page_number: int) -> list[dict]:
    """Structured table detection for one PDF page.

    Preserves row/column relationships, headers, and page provenance; the
    serialized rows keep their page tag so downstream reasoning never assigns
    a topic to the wrong section. Returns [] for pages without tables.
    """
    if not hasattr(page, "find_tables"):
        return []
    try:
        finder = page.find_tables()
        found = finder.tables if finder is not None else []
    except Exception:
        return []
    tables = []
    for i, t in enumerate(found):
        try:
            rows = t.extract() or []
        except Exception:
            rows = []
        rows = [[(c or "") if c is not None else "" for c in row] for row in rows]
        tables.append({
            "index": i,
            "page": page_number,
            "header": list(rows[0]) if rows else [],
            "rows": rows,
            "rowCount": len(rows),
            "columnCount": max((len(r) for r in rows), default=0),
            "bbox": list(t.bbox) if t.bbox else None,
        })
    return tables


def _render_table(t: dict) -> str:
    """Serialize a table preserving row/column structure and its page tag."""
    rows = t.get("rows") or []
    lines = [f"[TABLE {t.get('page')}.{t.get('index')}] ({t.get('rowCount')} rows x {t.get('columnCount')} columns)"]
    for r in rows:
        lines.append(" | ".join(str(c or "").strip() for c in r))
    lines.append(f"[/TABLE {t.get('page')}.{t.get('index')}]")
    return "\n".join(lines)


def _pseudo_tables_from_text(text: str, page_number: int) -> list[dict]:
    """Table structure inference for text already separated by pipes/tabs.

    Real ruled tables are found by fitz's table finder; text-based documents
    (or PDFs whose tables lack ruling lines) keep their explicit cell
    separators and get row/column structure recorded here so the same
    relationship metadata is available and feature detection sees the table."""
    table_like = [line.strip() for line in (text or "").splitlines() if line.strip()]
    table_like = [l for l in table_like if l.count("|") >= 1 and l.count("|") < 6]
    if len(table_like) < 2:
        return []
    rows = []
    for l in table_like:
        cells = [c.strip() for c in l.split("|")]
        if len(cells) < 2:
            continue
        rows.append(cells)
    if len(rows) < 2:
        return []
    cols = max(len(r) for r in rows)
    return [{
        "index": 0,
        "page": page_number,
        "header": list(rows[0]),
        "rows": rows,
        "rowCount": len(rows),
        "columnCount": cols,
        "bbox": None,
        "inferred_from_separators": True,
    }]


def _build_page_text(page, page_number: int) -> tuple[str, list[dict]]:
    """Reading-order page text with structured tables preserved.

    When a page contains ruled tables, the flat text that belongs to a table
    region is replaced by the serialized table (so columns/rows stay intact and
    topics stay under their own section heading). Text that already separates
    cells with pipes keeps its text (order preserved) but has explicit table
    structure attached. Other pages use the plain text layer unchanged.
    """
    tables = _extract_tables(page, page_number)
    if not tables:
        raw = _safe_text(page.get_text("text"))
        pseudo = _pseudo_tables_from_text(raw, page_number)
        return raw, (pseudo or tables)

    blocks = []
    try:
        for b in page.get_text("blocks"):
            if b[6] != 0 or not b[4]:
                continue
            blocks.append({"x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "text": str(b[4])})
    except Exception:
        return _safe_text(page.get_text("text")), tables

    items = []
    for blk in blocks:
        cbx = (blk["x0"] + blk["x1"]) / 2
        cby = (blk["y0"] + blk["y1"]) / 2
        inside_table = any(
            tb.get("bbox") and tb["bbox"][0] - 2 <= cbx <= tb["bbox"][2] + 2
            and tb["bbox"][1] - 2 <= cby <= tb["bbox"][3] + 2
            for tb in tables
        )
        if inside_table:
            continue
        t = _safe_text(blk["text"])
        if t:
            items.append((blk["y0"], "text", t))
    for tb in tables:
        items.append(((tb.get("bbox") or [0, 0, 0, 0])[1], "table", tb))

    items.sort(key=lambda it: it[0])
    combined = "\n".join(
        payload if kind == "text" else _render_table(payload)
        for _, kind, payload in items
    )
    return _safe_text(combined), tables


async def _extract_with_visual_fallback(data: bytes, mime: str | None = None,
                                        run_ocr=None) -> dict | None:
    """Attempt visual/OCR extraction when text extraction is empty/sparse.

    Renders every PDF page to an image and extracts text visually (OCR).
    Returns rendered-page evidence with text when OCR could read it; pages OCR
    could not read stay labeled 'visual' with empty text — honest, never
    fabricated. Rendered images are not persisted (dropped before returning).
    """
    try:
        import fitz
    except Exception:
        return None

    # Log PDF size validation for production debugging
    if not data:
        import logging
        logging.warning("PDF extraction failed: empty data")
        return None
    if len(data) < 100:
        import logging
        logging.warning(f"PDF extraction failed: data too small ({len(data)} bytes)")
        return None
    # Check PDF header - valid PDFs start with "%PDF-"
    if not data[:5] == b"%PDF-":
        import logging
        logging.warning(f"PDF extraction failed: invalid PDF header")
        return None

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        import logging
        logging.exception("PyMuPDF failed to open PDF stream")
        return None

    pages = []
    try:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            img_data = pix.tobytes(output="png")
            pages.append({
                "page": i + 1,
                "text": "",
                "image": base64.b64encode(img_data).decode("ascii"),
                "source": "visual",
            })
    finally:
        doc.close()

    if pages and run_ocr:
        try:
            texts = await run_ocr(data, mime, pages)
        except Exception:
            texts = {}
        for p in pages:
            t = (texts or {}).get(p["page"])
            if t and t.strip():
                p["text"] = _safe_text(t)
                p["source"] = "visual_ocr"

    quality = _assess_extraction_quality(pages)
    # Images are only transit supports for OCR; never persist base64 page
    # images on the extraction record.
    for p in pages:
        p.pop("image", None)

    return {
        "pageCount": len(pages),
        "extractionSource": "visual_ocr" if any(p.get("text") for p in pages) else "visual",
        "textLayerPages": 0,
        "ocrPages": sum(1 for p in pages if p.get("source") == "visual_ocr"),
        "extractionQuality": quality["quality"],
        "qualityMetrics": quality["metrics"],
        "pages": pages,
    }


def extract_pdf_pages(data: bytes) -> dict | None:
    """Extract text and tables from a PDF file's text layer.
    
    Logs detailed metrics for production debugging without exposing content.
    """
    import logging
    
    # Log PDF size validation for production debugging
    if not data:
        logging.warning("extract_pdf_pages: empty data")
        return None
    if len(data) < 100:
        logging.warning(f"extract_pdf_pages: data too small ({len(data)} bytes)")
        return None
    # Check PDF header - valid PDFs start with "%PDF-"
    if not data[:5] == b"%PDF-":
        logging.warning(f"extract_pdf_pages: invalid PDF header (got {data[:20]!r})")
        return None
    
    try:
        import fitz
    except Exception as e:
        logging.exception(f"PyMuPDF module not available: {type(e).__name__}")
        return None
    
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        logging.exception(f"PyMuPDF failed to open PDF: {type(e).__name__}: {e}")
        return None
    pages = []
    all_tables = []
    try:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            text, tables = _build_page_text(page, i + 1)
            page_rec = {
                "page": i + 1,
                "text": text,
                "source": "text_layer" if text else "ocr",
            }
            if tables:
                page_rec["tables"] = tables
                all_tables.extend(tables)
            pages.append(page_rec)
    finally:
        doc.close()
    if not pages:
        logging.info("extract_pdf_pages: no pages extracted")
        return None
    stats = _extraction_stats(pages)
    quality = _assess_extraction_quality(pages)
    logging.info(f"extract_pdf_pages: {len(pages)} pages, {stats['extractionSource']}, quality={quality['quality']}, tables={len(all_tables)}")
    # Log page-level metrics without exposing content
    pages_with_text = sum(1 for p in pages if (p.get("text") or "").strip())
    total_text = sum(len((p.get("text") or "").strip()) for p in pages)
    logging.info(f"extract_pdf_pages: pages_with_text={pages_with_text}, total_text_chars={total_text}")
    return {
        **stats,
        "pages": pages,
        "tables": all_tables,
        "extractionQuality": quality["quality"],
        "qualityMetrics": quality["metrics"],
    }


def _extraction_stats(pages: list[dict]) -> dict:
    """Kind/counts across pages. 'ocr_required' means pages still have no
    readable text after OCR — never silently 'read'; 'ocr'/'mixed'/'text_layer'
    mean those pages were actually read, and from what source."""
    text_pages = [p for p in pages if p["source"] == "text_layer"]
    ocr_pages = [p for p in pages if p["source"] == "ocr"]
    plain_pages = [p for p in pages if p["source"] == "plain_text"]
    unread = [p for p in pages if not p.get("text")]
    if plain_pages:
        kind = "plain_text"
    elif unread and text_pages:
        kind = "mixed"
    elif unread:
        kind = "ocr_required"
    elif ocr_pages and not text_pages:
        kind = "ocr"
    elif ocr_pages:
        kind = "mixed"
    else:
        kind = "text_layer"
    return {
        "pageCount": len(pages),
        "extractionSource": kind,
        "textLayerPages": len(text_pages),
        "ocrPages": len(ocr_pages),
    }


def _render_needed_pages(data: bytes, page_numbers) -> dict[int, str]:
    """Render specific PDF pages to PNG (base64) for visual recovery."""
    try:
        import fitz
    except Exception:
        return {}
    wanted = set(page_numbers)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return {}
    out = {}
    try:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            if (i + 1) not in wanted:
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            out[i + 1] = base64.b64encode(pix.tobytes(output="png")).decode("ascii")
    finally:
        doc.close()
    return out


def _page_needs_ocr(p: dict) -> bool:
    text = (p.get("text") or "").strip()
    if not text:
        return True
    if _is_corrupted(text):
        return True
    return False


async def _fill_ocr(data: bytes, mime: str | None, extracted: dict, run_ocr) -> None:
    """Row OCR recovery for pages the text layer could not read (in place).

    Given the extraction result, determine which pages need visual evidence:
      - pages with no text at all (scanned/image, or missing large portions)
      - pages flagged corrupted
      - when the whole document read as sparse, additionally pages whose text
        is suspiciously short (a header where the body belongs)
    Those pages are rendered to images and the app's OCR capability reads
    them. Pages the text layer read well keep their text_layer reading;
    recovered pages are labeled 'ocr'/'visual_ocr' honestly with the text
    layer preview preserved on 'textLayerPreview'. Nothing is fabricated:
    a page OCR cannot read stays labeled empty.
    """
    pages = extracted.get("pages") or []
    if not pages or not run_ocr:
        return
    quality = extracted.get("extractionQuality") or _assess_extraction_quality(pages)["quality"]

    needed = [p for p in pages if _page_needs_ocr(p)]
    if quality == "sparse":
        for p in pages:
            if len((p.get("text") or "").strip()) < SHORT_PAGE_CHARS and p not in needed:
                needed.append(p)
    if not needed:
        return

    rendered = _render_needed_pages(data, {p["page"] for p in needed})
    for p in needed:
        if p["page"] in rendered:
            p["image"] = rendered[p["page"]]

    texts = await run_ocr(data, mime, needed)
    for p in needed:
        t = (texts or {}).get(p["page"])
        if not t or not t.strip():
            continue
        t = _safe_text(t)
        original = (p.get("text") or "").strip()
        if not original:
            p["text"] = t
            p["ocr"] = True
            # source stays 'ocr' — the page had no text layer and OCR read it
        elif _is_corrupted(original) or len(t) > len(original) * 1.5:
            # The text layer was broken or clearly incomplete; the rendered
            # page restored the content. Keep the original for reference.
            p["textLayerPreview"] = original[:500]
            p["text"] = t
            p["ocr"] = True
            if p.get("image"):
                p["source"] = "visual_ocr"

    for p in pages:
        p.pop("image", None)


async def extract_document_pages_with_ocr(data: bytes, mime: str | None = None,
                                          run_ocr=None) -> dict | None:
    """Page extraction plus visual/OCR recovery, with automatic fallback.

    run_ocr(data, mime, pages) is the app's OCR capability: it reads the
    rendered pages and returns {page_number: verbatim text}. OCR-derived pages
    stay labeled source='ocr'/'visual_ocr' with their page number; pages OCR
    could not read remain empty — labeled, honest, never fabricated.
    Question-agnostic: every page is transcribed; relevance selection happens
    later in analysis.

    If normal text extraction fails or is of poor quality (empty/sparse/
    partial sections), the missing/short/corrupted pages are rendered and read
    visually, and the two evidence sources are combined. Quality is
    re-assessed after recovery so downstream consumers reflect what was
    actually acquired.
    """
    extracted = extract_document_pages(data, mime)
    if not extracted:
        if mime and "pdf" in mime.lower():
            return await _extract_with_visual_fallback(data, mime, run_ocr)
        return None

    if mime and "pdf" in mime.lower():
        # ponytail: OCR recovery on pages with missing/short/corrupted text;
        # whole-document visual fallback only when nothing was read at all.
        await _fill_ocr(data, mime, extracted, run_ocr)

    quality = _assess_extraction_quality(extracted.get("pages") or [])
    extracted["extractionQuality"] = quality["quality"]
    extracted["qualityMetrics"] = quality["metrics"]
    extracted.update(_extraction_stats(extracted["pages"]))
    return extracted


def extract_document_pages(data: bytes, mime: str | None = None) -> dict | None:
    """Extract a document into numbered, source-labeled pages, or None when no
    readable content is available (evidence unavailable, not 'no metadata')."""
    mime = (mime or "").lower()
    if "pdf" in mime:
        return extract_pdf_pages(data)
    text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        return None
    pages = [{"page": 1, "text": text.strip(), "source": "plain_text"}]
    quality = _assess_extraction_quality(pages)
    return {
        "pageCount": 1,
        "extractionSource": "plain_text",
        "textLayerPages": 1,
        "ocrPages": 0,
        "extractionQuality": quality["quality"],
        "qualityMetrics": quality["metrics"],
        "tables": [],
        "pages": pages,
    }


if __name__ == "__main__":  # self-check: fails loudly if extraction regresses
    # plain text → single page, plain_text source
    r = extract_document_pages(b"Hello evidence world", "text/plain")
    assert r["extractionSource"] == "plain_text" and r["pageCount"] == 1
    assert r["pages"][0]["source"] == "plain_text" and r["pages"][0]["text"].startswith("Hello")
    assert r["extractionQuality"] == "complete", r["extractionQuality"]

    # unreadable → None (evidence unavailable), never fabricated text
    assert extract_document_pages(b"", "text/plain") is None

    try:
        import fitz
    except Exception:
        print("fitz not installed — skipping PDF self-check")
    else:
        import io
        pdf = fitz.open()
        for body in (
            "Lease term is 24 months, renewable automatically for successive 12-month periods.",
            "Monthly rent is fixed at five thousand dollars for the first twelve months.",
        ):
            pg = pdf.new_page()
            pg.insert_text((72, 72), body)
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        data = buf.getvalue()
        r = extract_document_pages(data, "application/pdf")
        assert r["pageCount"] == 2 and r["extractionSource"] == "text_layer", r
        assert [p["page"] for p in r["pages"]] == [1, 2]
        assert all(p["source"] == "text_layer" for p in r["pages"])
        assert "24 months" in r["pages"][0]["text"]
        assert r["extractionQuality"] == "complete", r["extractionQuality"]

        blank = fitz.open()
        blank.new_page()
        buf2 = io.BytesIO()
        blank.save(buf2)
        blank.close()
        r2 = extract_document_pages(buf2.getvalue(), "application/pdf")
        assert r2["extractionSource"] == "ocr_required", r2
        assert r2["pages"][0]["source"] == "ocr" and r2["pages"][0]["text"] == ""
        assert r2["extractionQuality"] == "empty", r2["extractionQuality"]
        assert r2["qualityMetrics"]["coverage"] == 0.0

        import asyncio

        async def _fake_ocr(data, mime, pages):
            return {p["page"]: f"This page contains the full OCR transcription for page {p['page']}."
                    for p in pages}

        async def _ocr_run():
            return await extract_document_pages_with_ocr(
                buf2.getvalue(), "application/pdf", _fake_ocr)

        r3 = asyncio.run(_ocr_run())
        # After fallback with visual OCR, source is visual_ocr (page rendered + OCR'd)
        assert r3["extractionSource"] in ("ocr", "visual_ocr"), r3
        assert r3["pages"][0]["source"] in ("ocr", "visual_ocr")
        assert r3["pages"][0]["text"].startswith("This page contains the full OCR transcription")
        assert r3["extractionQuality"] in ("complete", "partial"), r3["extractionQuality"]
    print("document_extract self-check OK")