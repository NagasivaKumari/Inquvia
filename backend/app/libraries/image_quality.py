"""Image quality metrics — resolution, blur, compression/recompression indicators."""
from __future__ import annotations

import io

from ..libraries import image_forensics


def _blur_score(buf: bytes) -> dict:
    """Laplacian variance blur estimate (higher = sharper)."""
    try:
        import cv2
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(buf)) as img:
            gray = np.array(img.convert("L"))
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(lap.var())
        if variance < 50:
            band = "likely_blurry"
        elif variance < 150:
            band = "moderate_sharpness"
        else:
            band = "likely_sharp"
        return {"available": True, "laplacianVariance": round(variance, 2), "sharpnessBand": band}
    except ImportError:
        return {"available": False, "reason": "opencv not installed"}
    except Exception as exc:
        return {"available": False, "reason": str(exc)[:200]}


def analyze(buf: bytes, mime: str | None = None, forensics: dict | None = None) -> dict:
    from PIL import Image

    sig = forensics or image_forensics.analyze_image(buf, mime)
    blur = _blur_score(buf)
    width = height = None
    megapixels = None
    try:
        with Image.open(io.BytesIO(buf)) as img:
            width, height = img.size
            megapixels = round((width * height) / 1_000_000, 2)
    except Exception:
        pass

    resolution_band = "unknown"
    if megapixels is not None:
        if megapixels < 0.3:
            resolution_band = "very_low"
        elif megapixels < 1.0:
            resolution_band = "low"
        elif megapixels < 8:
            resolution_band = "moderate"
        else:
            resolution_band = "high"

    recompression = {}
    if sig.get("estimatedQuality") is not None:
        recompression["estimatedJpegQuality"] = sig["estimatedQuality"]
    if sig.get("jpegQuantizationStandard") is False:
        recompression["nonStandardQuantization"] = True
    ela = sig.get("ela") or {}
    if ela:
        recompression["elaMeanErrorPct"] = ela.get("meanErrorPct")
        recompression["elaElevatedBlocks"] = ela.get("elevatedErrorBlocks")

    return {
        "width": width,
        "height": height,
        "megapixels": megapixels,
        "resolutionBand": resolution_band,
        "blur": blur,
        "recompression": recompression,
        "disclaimer": "Quality metrics describe the file — not authenticity.",
    }


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = ["IMAGE QUALITY (observed metrics):"]
    if result.get("width") and result.get("height"):
        lines.append(
            f"- resolution: {result['width']}x{result['height']} "
            f"({result.get('megapixels')} MP, band={result.get('resolutionBand')})"
        )
    blur = result.get("blur") or {}
    if blur.get("available"):
        lines.append(
            f"- blur/sharpness: Laplacian variance={blur.get('laplacianVariance')} "
            f"({blur.get('sharpnessBand')})"
        )
    rec = result.get("recompression") or {}
    if rec.get("estimatedJpegQuality") is not None:
        lines.append(f"- estimated JPEG quality: {rec['estimatedJpegQuality']}")
    if rec.get("elaMeanErrorPct") is not None:
        lines.append(
            f"- ELA mean error: {rec['elaMeanErrorPct']}% "
            f"({rec.get('elaElevatedBlocks', 0)} elevated blocks)"
        )
    return "\n".join(lines)
