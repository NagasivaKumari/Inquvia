"""Document-image forensic analysis — layout, text regions, signature heuristics."""
from __future__ import annotations

import io


def _document_layout(buf: bytes) -> dict:
    """Heuristic document layout from aspect ratio and edge density."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(buf)) as img:
            w, h = img.size
            aspect = w / h if h else 0
            gray = img.convert("L")
            # Sample edge density via simple gradient approximation (no opencv required).
            px = gray.resize((min(w, 400), min(h, 400))).load()
            gw, gh = gray.size
            sw, sh = min(w, 400), min(h, 400)
            edges = 0
            total = 0
            for y in range(1, sh - 1):
                for x in range(1, sw - 1):
                    a = px[x, y]
                    b = px[x + 1, y]
                    c = px[x, y + 1]
                    if abs(a - b) + abs(a - c) > 40:
                        edges += 1
                    total += 1
            edge_density = round(edges / max(total, 1), 4)
            portrait_doc = 0.65 <= aspect <= 0.85
            landscape_doc = 1.2 <= aspect <= 1.5
            likely_document = (portrait_doc or landscape_doc) and edge_density > 0.08
            return {
                "width": w,
                "height": h,
                "aspectRatio": round(aspect, 3),
                "edgeDensity": edge_density,
                "likelyDocumentLayout": likely_document,
                "orientation": "portrait" if aspect < 1 else "landscape" if aspect > 1 else "square",
            }
    except Exception as exc:
        return {"error": str(exc)[:200]}


def _signature_regions(buf: bytes) -> dict:
    """Heuristic signature/stamp regions — bottom third high-ink areas."""
    try:
        import cv2
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(buf)) as img:
            arr = np.array(img.convert("L"))
        h, w = arr.shape
        bottom = arr[int(h * 0.65):, :]
        _, thresh = cv2.threshold(bottom, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if 20 < cw < w * 0.6 and 10 < ch < h * 0.25:
                regions.append({
                    "x": int(x),
                    "y": int(y + int(h * 0.65)),
                    "width": int(cw),
                    "height": int(ch),
                })
        regions = sorted(regions, key=lambda r: r["width"] * r["height"], reverse=True)[:5]
        return {
            "available": True,
            "candidateSignatureRegions": regions,
            "regionCount": len(regions),
            "note": "Regions are heuristic ink-blob candidates — not verified signatures.",
        }
    except ImportError:
        return {"available": False, "reason": "opencv not installed"}
    except Exception as exc:
        return {"available": False, "reason": str(exc)[:200]}


def analyze(buf: bytes, ocr_text: str | None = None) -> dict:
    layout = _document_layout(buf)
    signatures = _signature_regions(buf)
    doc_keywords = []
    if ocr_text:
        lower = ocr_text.lower()
        for kw in ("invoice", "receipt", "certificate", "license", "passport", "total", "signature", "authorized"):
            if kw in lower:
                doc_keywords.append(kw)
    return {
        "layout": layout,
        "signatures": signatures,
        "documentKeywordsInText": doc_keywords,
        "likelyDocumentImage": bool(
            layout.get("likelyDocumentLayout") or doc_keywords
        ),
        "disclaimer": "Layout/signature heuristics do not authenticate documents.",
    }


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = ["DOCUMENT IMAGE ANALYSIS (observed):"]
    layout = result.get("layout") or {}
    if layout.get("likelyDocumentLayout"):
        lines.append(
            f"- likely document layout ({layout.get('orientation')}, "
            f"aspect={layout.get('aspectRatio')}, edge density={layout.get('edgeDensity')})"
        )
    else:
        lines.append("- document layout not strongly indicated by geometry/edges")
    if result.get("documentKeywordsInText"):
        lines.append(f"- document keywords in OCR text: {', '.join(result['documentKeywordsInText'])}")
    sig = result.get("signatures") or {}
    if sig.get("available"):
        lines.append(f"- candidate signature/stamp regions: {sig.get('regionCount', 0)}")
    lines.append(f"- note: {result.get('disclaimer')}")
    return "\n".join(lines)
