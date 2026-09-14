"""Privacy & PII detection for images — faces, codes, and text patterns."""
from __future__ import annotations

import re

# Regex heuristics for PII in extracted text (OCR output).
_PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(\d{2,4}\)|\d{2,4})[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card_like": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "license_plate_us": re.compile(r"\b[A-Z0-9]{1,3}[-\s]?[A-Z0-9]{2,4}[-\s]?[A-Z0-9]{2,4}\b"),
    "address_like": re.compile(
        r"\b\d{1,5}\s+[A-Za-z0-9.\s]{3,40}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr| Blvd)\b",
        re.I,
    ),
}


def detect_faces(buf: bytes) -> dict:
    """Face detection via OpenCV Haar cascades when available."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
        import io

        with Image.open(io.BytesIO(buf)) as img:
            gray = np.array(img.convert("L"))
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(24, 24))
        regions = [
            {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
            for (x, y, w, h) in faces
        ]
        return {
            "available": True,
            "faceCount": len(regions),
            "regions": regions[:20],
            "note": "Face regions detected — do not infer identity from detection alone.",
        }
    except ImportError:
        return {"available": False, "faceCount": None, "reason": "opencv not installed"}
    except Exception as exc:
        return {"available": False, "faceCount": None, "reason": str(exc)[:200]}


def decode_barcodes(buf: bytes) -> dict:
    """QR / barcode decoding via pyzbar when available."""
    try:
        from pyzbar.pyzbar import decode as zbar_decode
        from PIL import Image
        import io

        with Image.open(io.BytesIO(buf)) as img:
            codes = zbar_decode(img.convert("RGB"))
        decoded = []
        for c in codes:
            decoded.append({
                "type": c.type,
                "data": (c.data.decode("utf-8", errors="replace") if c.data else "")[:500],
                "rect": {"x": c.rect.left, "y": c.rect.top, "w": c.rect.width, "h": c.rect.height},
            })
        return {"available": True, "codeCount": len(decoded), "codes": decoded[:10]}
    except ImportError:
        return {"available": False, "codeCount": 0, "reason": "pyzbar not installed"}
    except Exception as exc:
        return {"available": False, "codeCount": 0, "reason": str(exc)[:200]}


def scan_text_pii(text: str) -> dict:
    """Find PII-like patterns in OCR text."""
    findings = {}
    for name, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(text or "")
        if matches:
            # Redact middle portions for evidence record safety.
            redacted = []
            for m in matches[:5]:
                s = str(m)
                if len(s) > 6:
                    redacted.append(s[:2] + "…" + s[-2:])
                else:
                    redacted.append("…")
            findings[name] = {"count": len(matches), "samplesRedacted": redacted}
    return findings


def analyze(buf: bytes, ocr_text: str | None = None) -> dict:
    faces = detect_faces(buf)
    codes = decode_barcodes(buf)
    pii = scan_text_pii(ocr_text or "")
    sensitive = bool(
        (faces.get("faceCount") or 0) > 0
        or (codes.get("codeCount") or 0) > 0
        or pii
    )
    return {
        "faces": faces,
        "barcodes": codes,
        "textPii": pii,
        "sensitiveContentDetected": sensitive,
        "disclaimer": (
            "Detection indicates possible sensitive content — not identity verification. "
            "Redacted samples are shown in evidence records for safety."
        ),
    }


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = ["PRIVACY / PII DETECTION (observed):"]
    faces = result.get("faces") or {}
    if faces.get("available") and faces.get("faceCount") is not None:
        lines.append(f"- faces detected: {faces['faceCount']}")
    elif not faces.get("available"):
        lines.append(f"- face detection unavailable: {faces.get('reason', 'unknown')}")
    codes = result.get("barcodes") or {}
    if codes.get("available"):
        lines.append(f"- QR/barcodes decoded: {codes.get('codeCount', 0)}")
    elif not codes.get("available"):
        lines.append(f"- QR/barcode decoding unavailable: {codes.get('reason', 'unknown')}")
    for kind, info in (result.get("textPii") or {}).items():
        lines.append(f"- text pattern '{kind}': {info.get('count')} match(es)")
    lines.append(f"- note: {result.get('disclaimer')}")
    return "\n".join(lines)
