"""Page-structured document extraction (PDF text layer / plain text).

Extraction is comprehensive and question-agnostic by design: every page is
retained with its page number and a label describing where its text came from
— a selectable text layer ("text_layer") or the rendered page ("ocr",
i.e. no selectable text, so anything read off it is OCR-derived). Choosing
which pages or passages are relevant to the user's question happens LATER, in
analysis; nothing in this module reads the question.

PDFs are read with PyMuPDF (fitz) when installed. When no extractor is
installed or a document yields no readable content, extraction returns None —
evidence unavailable — rather than fabricating text.
"""
import re

MAX_PAGES = 200  # ponytail: hard cap so a pathological PDF can't flood storage; raise if large scans are real inputs


def _safe_text(raw: str) -> str:
    return re.sub(r"\r\n?", "\n", raw or "").strip()


def extract_pdf_pages(data: bytes) -> dict | None:
    try:
        import fitz
    except Exception:
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return None
    pages = []
    try:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            text = _safe_text(page.get_text("text"))
            pages.append({
                "page": i + 1,
                "text": text,
                "source": "text_layer" if text else "ocr",
            })
    finally:
        doc.close()
    if not pages:
        return None
    stats = _extraction_stats(pages)
    return {**stats, "pages": pages}


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


async def extract_document_pages_with_ocr(data: bytes, mime: str | None = None,
                                          run_ocr=None) -> dict | None:
    """Page extraction plus OCR for pages without a text layer.

    run_ocr(data, mime, pages) is the app's OCR capability: it reads the
    attachment and returns {page_number: verbatim text} for the pages it could
    read. OCR-derived pages stay labeled source='ocr' with their page number;
    pages OCR could not read remain empty — labeled, honest, never fabricated.
    Question-agnostic: every page is transcribed; relevance selection happens
    later in analysis.
    """
    extracted = extract_document_pages(data, mime)
    if not extracted:
        return None
    ocr_pages = [p for p in extracted["pages"] if p.get("source") == "ocr"]
    if ocr_pages:
        texts = {}
        if run_ocr:
            try:
                texts = await run_ocr(data, mime, ocr_pages)
            except Exception:
                texts = {}
        for p in ocr_pages:
            t = (texts or {}).get(p["page"])
            if t and t.strip():
                p["text"] = _safe_text(t)
                p["ocr"] = True
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
    return {
        "pageCount": 1,
        "extractionSource": "plain_text",
        "textLayerPages": 1,
        "ocrPages": 0,
        "pages": [{"page": 1, "text": text.strip(), "source": "plain_text"}],
    }


if __name__ == "__main__":  # self-check: fails loudly if extraction regresses
    # plain text → single page, plain_text source
    r = extract_document_pages(b"Hello evidence world", "text/plain")
    assert r["extractionSource"] == "plain_text" and r["pageCount"] == 1
    assert r["pages"][0]["source"] == "plain_text" and r["pages"][0]["text"].startswith("Hello")

    # unreadable → None (evidence unavailable), never fabricated text
    assert extract_document_pages(b"", "text/plain") is None

    try:
        import fitz
    except Exception:
        print("fitz not installed — skipping PDF self-check")
    else:
        import io
        pdf = fitz.open()
        for body in ("Lease term is 24 months.", "Renewal is automatic."):
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

        blank = fitz.open()
        blank.new_page()
        buf2 = io.BytesIO()
        blank.save(buf2)
        blank.close()
        r2 = extract_document_pages(buf2.getvalue(), "application/pdf")
        assert r2["extractionSource"] == "ocr_required", r2
        assert r2["pages"][0]["source"] == "ocr" and r2["pages"][0]["text"] == ""

        import asyncio

        async def _fake_ocr(data, mime, pages):
            return {p["page"]: f"OCR text page {p['page']}" for p in pages}

        async def _ocr_run():
            return await extract_document_pages_with_ocr(
                buf2.getvalue(), "application/pdf", _fake_ocr)

        r3 = asyncio.run(_ocr_run())
        assert r3["extractionSource"] == "ocr", r3
        assert r3["pages"][0]["source"] == "ocr" and r3["pages"][0]["ocr"] is True
        assert r3["pages"][0]["text"].startswith("OCR text page 1")
    print("document_extract self-check OK")