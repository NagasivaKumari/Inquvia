"""Reproducible image-manipulation forensics (layer 5 of image investigations).

Deterministic, pure-Pillow + stdlib signals an examiner could re-run and get
the same answer: Error Level Analysis, a JPEG quality estimate from the
quantization table, metadata/tag consistency heuristics, and a perceptual
(difference) hash for near-duplicate matching. Nothing here is AI-inferred.

ponytail: ELA over full-res blocks only; per-region heatmaps and copy-move
detection are the known ceiling — add when a case actually needs spatial
localization, not before.
"""
import io
import struct

IMAGE_KINDS = {"image", "jpeg", "png", "gif", "webp", "bmp", "tiff"}

# Known editor software tags — presence is a fact, not proof of editing.
_EDITOR_SOFTWARE = (
    "adobe photoshop", "photoshop", "pixelmator", "gimp", "snapseed",
    "lightroom", "canon digital photo professional", "affinity photo",
    "skylum", "airbrush", "facetune", "afterlight", "vsco", "美图",
)


def load_bytes(file_path: str) -> bytes | None:
    from .. import db
    from ..libraries import storage

    stored = db.read_upload_file(file_path)
    if stored and stored[0]:
        return stored[0]
    p = storage.resolve_stored_path(file_path)
    if p:
        try:
            return p.read_bytes()
        except OSError:
            return None
    return None


def hamming_distance(h1: str, h2: str) -> int | None:
    """Bit differences between two equal-length hex dHash strings."""
    if not h1 or not h2 or len(h1) != len(h2):
        return None
    return sum(c1 != c2 for c1, c2 in zip(h1, h2))


def compare_images(buf1: bytes, buf2: bytes,
                   mime1: str | None = None, mime2: str | None = None) -> dict:
    """Deterministic two-image relationship assessment using dHash + dimensions."""
    from PIL import Image

    hash1 = perceptual_hash(buf1)
    hash2 = perceptual_hash(buf2)
    dist = hamming_distance(hash1, hash2)

    dims1 = dims2 = None
    fmt1 = fmt2 = "UNKNOWN"
    try:
        with Image.open(io.BytesIO(buf1)) as img:
            dims1 = img.size
            fmt1 = (img.format or "UNKNOWN").upper()
    except Exception:
        pass
    try:
        with Image.open(io.BytesIO(buf2)) as img:
            dims2 = img.size
            fmt2 = (img.format or "UNKNOWN").upper()
    except Exception:
        pass

    same_dims = dims1 == dims2 if dims1 and dims2 else None
    relationship = "different"
    confidence = "low"
    if dist is not None:
        if dist == 0:
            relationship = "exact_or_identical_hash"
            confidence = "high"
        elif dist <= 5:
            relationship = "near_duplicate_or_minor_edit"
            confidence = "high"
        elif dist <= 12:
            relationship = "likely_derivative_resized_or_cropped"
            confidence = "medium"
        elif dist <= 20:
            relationship = "related_similar_composition"
            confidence = "low"
        else:
            relationship = "different"
            confidence = "medium"

    transformations = []
    if same_dims is False and dist is not None and dist <= 12:
        transformations.append("probable_resize_or_crop")
    if fmt1 != fmt2 and fmt1 != "UNKNOWN" and fmt2 != "UNKNOWN":
        transformations.append("format_change")

    return {
        "perceptualHash1": hash1,
        "perceptualHash2": hash2,
        "hammingDistance": dist,
        "dimensions1": dims1,
        "dimensions2": dims2,
        "format1": fmt1,
        "format2": fmt2,
        "sameDimensions": same_dims,
        "relationship": relationship,
        "confidence": confidence,
        "probableTransformations": transformations,
    }


def describe_comparison(cmp: dict, label1: str = "image A", label2: str = "image B") -> str:
    """Human-readable comparison block for evidence records."""
    if not cmp:
        return ""
    lines = [
        f"COMPARISON ({label1} vs {label2}):",
        f"- dHash distance: {cmp.get('hammingDistance')} (0=identical perceptual hash)",
        f"- relationship: {cmp.get('relationship')} (confidence: {cmp.get('confidence')})",
    ]
    if cmp.get("dimensions1") and cmp.get("dimensions2"):
        lines.append(f"- dimensions: {cmp['dimensions1']} vs {cmp['dimensions2']}")
    if cmp.get("probableTransformations"):
        lines.append(f"- probable transformations: {', '.join(cmp['probableTransformations'])}")
    return "\n".join(lines)


def perceptual_hash(buf: bytes) -> str:
    """64-bit difference hash (dHash) hex string.

    Downscale to 9x8, convert to grayscale, then record whether each
    right-neighbour pixel is brighter than its left neighbour. Near-duplicates
    (re-encodes, crops, slight rescales) share most of the 64 bits.
    """
    from PIL import Image

    try:
        with Image.open(io.BytesIO(buf)) as img:
            img = img.convert("L").resize((9, 8), Image.LANCZOS)
            px = list(img.getdata())
    except Exception:
        return ""
    bits = 0
    for y in range(8):
        for x in range(8):
            left = px[y * 9 + x]
            right = px[y * 9 + x + 1]
            bits = (bits << 1) | (1 if right > left else 0)
    return f"{bits:016x}"


def _jpeg_quality_from_dqt(dqt: list[int]) -> int | None:
    """Estimate JPEG quality (0-100) from the luminance quantization table.

    Standard tables embed the base-50 scale; non-standard tables are either a
    quality-scaled re-encode or camera-tuned, so the estimate is approximate —
    reported as an estimate, never exact.
    """
    # Standard JPEG Annex K luminance table (the quality-50 reference).
    std = [
        16, 11, 10, 16, 24, 40, 51, 61,
        12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56,
        14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77,
        24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101,
        72, 92, 95, 98, 112, 100, 103, 99,
    ]
    if len(dqt) < 64:
        return None
    if dqt == std:
        return 50
    if dqt[:64] == std:  # already equal; same thing
        return 50
    # Scaled tables keep a scalar ratio vs the standard table. Average the
    # per-cell ratio, clamped: 2 = ~1 (quality 50 → ~90+ for most encoders).
    ratios = []
    for i in range(64):
        if std[i] and dqt[i] > 0:
            ratios.append(dqt[i] / std[i])
    if not ratios:
        return None
    q = 5000 / (sum(ratios) / len(ratios) * 100)  # IJG luminance-scale relation
    return int(min(100, max(1, round(q))))


def _read_jpeg_quantization(buf: bytes) -> tuple[list[int] | None, bool]:
    """Parse the first SOS-preceding DQT segment (luminance table) from a raw
    JPEG. Returns (table, standard_like). Never raises on malformed input."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(buf)) as img:
            if img.format != "JPEG":
                return None, False
            dqt = img.quantization
            if isinstance(dqt, dict) and 0 in dqt:
                table = dqt[0]
                if isinstance(table, (list, tuple)):
                    return list(table), False
    except Exception:
        pass
    # Fallback: raw segment scan (Pillow cache may not expose tables).
    pos = 2
    n = len(buf)
    while pos + 4 <= n and buf[pos] == 0xFF:
        if buf[pos + 1] in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF — DQT must precede
            return None, False
        if buf[pos + 1] == 0xDB:  # DQT
            seg_len = struct.unpack(">H", buf[pos + 2:pos + 4])[0]
            body = buf[pos + 4:pos + 2 + seg_len]
            if len(body) >= 65:
                return list(body[1:65]), True
            return None, False
        seg_len = struct.unpack(">H", buf[pos + 2:pos + 4])[0]
        pos += 2 + seg_len
    return None, False


def error_level_analysis(buf: bytes, *, reencode_quality: int = 90) -> dict | None:
    """ELA over 32x32 blocks: difference between the original and a copy that
    was decoded and re-encoded at `reencode_quality`.

    Uniformly edited areas usually show measurably different per-block error
    than the untouched image. Output is a per-block error distribution plus its
    spatial localization — a real observation with clear limits; it reports
    where error is elevated, never "this region was edited" by itself.

    Returns None when the image cannot be re-encoded lossily (GIF/PNG are
    lossless — ELA is not meaningful there).
    """
    from PIL import Image, ImageChops

    try:
        with Image.open(io.BytesIO(buf)) as img:
            if img.format not in ("JPEG", "WEBP"):
                return None
            img = img.convert("RGB")
            buf_re = io.BytesIO()
            img.save(buf_re, format=img.format or "JPEG", quality=reencode_quality)
            buf_re.seek(0)
            with Image.open(buf_re) as img2:
                img2 = img2.convert("RGB")
            diff = ImageChops.difference(img, img2).convert("L")
    except Exception:
        return None

    w, h = diff.size
    block = 32
    rows, cols = max(1, h // block), max(1, w // block)
    grid = [[0.0] * cols for _ in range(rows)]
    for row in range(rows):
        for col in range(cols):
            x, y = col * block, row * block
            crop = diff.crop((x, y, min(x + block, w), min(y + block, h)))
            pixels = list(crop.getdata())
            if not pixels:
                continue
            grid[row][col] = sum(pixels) / (len(pixels) * 255.0) * 100  # percent error
    diffs = [grid[row][col] for row in range(rows) for col in range(cols)]
    mean_err = round(sum(diffs) / len(diffs), 3) if diffs else 0.0
    # The cleanest (minimum-error) block is the untouched reference; anything
    # markedly above it is where re-encode error concentrates. A 2x multiplier
    # with a 4% floor beats a mean-relative threshold, which breaks when the
    # contamination covers half the frame.
    threshold = max(4.0, min(diffs) * 2.0)
    elevated = [[grid[row][col] > threshold for col in range(cols)] for row in range(rows)]

    # Spatial localization: merge contiguous elevated runs (row by row) into
    # minimal pixel rectangles, so the analyst sees WHERE error concentrates.
    active: list[dict] = []
    for row in range(rows):
        col = 0
        while col < cols:
            if not elevated[row][col]:
                col += 1
                continue
            start = col
            while col < cols and elevated[row][col]:
                col += 1
            run = (start, col - 1)
            merged = None
            for r in active:
                if r["rowEnd"] == row - 1 and not (run[1] < r["col"] or run[0] > r["colEnd"]):
                    merged = r
                    break
            if merged:
                merged["rowEnd"] = row
                merged["col"] = min(merged["col"], run[0])
                merged["colEnd"] = max(merged["colEnd"], run[1])
            else:
                active.append({"row": row, "rowEnd": row, "col": run[0], "colEnd": run[1]})
    elevated_regions = [
        {
            "x": r["col"] * block,
            "y": r["row"] * block,
            "width": (r["colEnd"] - r["col"] + 1) * block,
            "height": (r["rowEnd"] - r["row"] + 1) * block,
        }
        for r in active
    ]

    # Downsampled text heatmap (cols capped at 64) so the analysis model can
    # SEE the localization pattern even without a rendered image.
    step = max(1, (cols + 63) // 64)
    heat_lines = []
    for row in range(0, rows, max(1, step)):
        cells = []
        for col in range(0, cols, step):
            vals = [
                grid[r][c]
                for r in range(row, min(row + step, rows))
                for c in range(col, min(col + step, cols))
            ]
            peak = max(vals) if vals else 0.0
            cells.append("#" if peak > threshold else ("." if peak <= mean_err else ":"))
        heat_lines.append("".join(cells))
    heatmap = "\n".join(heat_lines)

    high_count = sum(1 for v in diffs if v > threshold)
    return {
        "reencodeQuality": reencode_quality,
        "blockCount": len(diffs),
        "meanErrorPct": mean_err,
        "maxErrorPct": round(max(diffs), 3) if diffs else 0.0,
        "elevatedErrorBlocks": high_count,
        "elevatedRegions": elevated_regions,
        "heatmap": heatmap,
        "errorVariance": round(sum((d - mean_err) ** 2 for d in diffs) / len(diffs), 3),
        "uniform": bool(high_count == 0 and mean_err < 2.0),
        "estimate": (
            "Low, spatially uniform re-encode error" if mean_err < 2.0 and not elevated_regions
            else "Elevated or uneven re-encode error — see block metrics and heatmap"
        ),
    }


def metadata_tamper_signals(buf: bytes) -> dict:
    """Metadata/tag consistency heuristics.

    All signals are recorded facts about the container: EXIF date parity,
    presence of known editor software tags, thumbnail divergence, and PNG
    timestamp/software chunks. Consistency does NOT prove authenticity and
    mismatch does NOT prove editing — the analyzer reasons over them.
    """
    from PIL import Image
    from PIL.ExifTags import Base as EBase

    out = {"warnings": []}
    try:
        with Image.open(io.BytesIO(buf)) as img:
            if img.format == "PNG":
                txt = getattr(img, "text", None)
                if isinstance(txt, dict):
                    soft = (txt.get("Software") or txt.get("software") or "").lower()
                    if "tIME" in [k.lower() for k in img.info.keys()]:
                        out["pngHasTimeChunk"] = True
                    out["pngSoftware"] = txt.get("Software") or txt.get("software")
            exif = img.getexif()
            if exif:
                def _get(*tags):
                    for t in tags:
                        try:
                            v = exif.get(t)
                            if v:
                                return str(v)
                        except Exception:
                            continue
                    return None
                original = _get(EBase.DateTimeOriginal)
                digitized = _get(EBase.DateTimeDigitized)
                if original and digitized and original != digitized:
                    out["dateMismatch"] = True
                elif original:
                    out["hasCaptureDate"] = True
                soft = _get(EBase.Software)
                if soft:
                    out["software"] = soft
                    lowered = soft.lower()
                    out["editorIdentified"] = any(
                        e in lowered for e in _EDITOR_SOFTWARE
                    )
                make = _get(EBase.Make)
                model = _get(EBase.Model)
                if make:
                    out["cameraMake"] = make
                if model:
                    out["cameraModel"] = model
                try:
                    out["hasGps"] = bool(exif.get_ifd(EBase.GPSInfo))
                except Exception:
                    out["hasGps"] = False
            else:
                out["exifAbsent"] = True
    except Exception:
        out["error"] = "metadata parse failed"
    return out


def analyze_image(buf: bytes, mime: str | None = None) -> dict:
    """Bundle the deterministic forensics layers into one structure."""
    from PIL import Image

    result = {
        "perceptualHash": perceptual_hash(buf),
        "tamperSignals": metadata_tamper_signals(buf),
    }
    try:
        with Image.open(io.BytesIO(buf)) as img:
            fmt = (img.format or "UNKNOWN").upper()
            result["format"] = fmt
            result["mimeType"] = mime or (
                {  # fall back only within the formats we know
                    "JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif",
                    "WEBP": "image/webp", "BMP": "image/bmp", "TIFF": "image/tiff",
                }.get(fmt, "application/octet-stream")
            )
    except Exception:
        result["format"] = "UNKNOWN"
    if result["format"] == "JPEG":
        dqt, raw = _read_jpeg_quantization(buf)
        if dqt:
            result["jpegQuantizationStandard"] = raw
            q = _jpeg_quality_from_dqt(dqt)
            if q is not None:
                result["estimatedQuality"] = q
        ela = error_level_analysis(buf)
        if ela:
            result["ela"] = ela
    return result


def describe(buf: bytes, mime: str | None = None, sig: dict | None = None) -> dict:
    """Structured forensics block compliant with EvidenceRecord schema."""
    sig = sig or analyze_image(buf, mime)
    lines = []
    if sig.get("perceptualHash"):
        lines.append(f"Perceptual hash: {sig['perceptualHash']}")
    if sig.get("estimatedQuality") is not None:
        lines.append(f"Estimated JPEG quality: {sig['estimatedQuality']} (approximate)")
    if sig.get("jpegQuantizationStandard"):
        lines.append("JPEG quantization suggests re-encode")
    
    # Metadata signals
    if "tamperSignals" in sig:
        t = sig["tamperSignals"]
        if t.get("exifAbsent"):
            lines.append("No EXIF data present")
        if t.get("dateMismatch"):
            lines.append("EXIF date inconsistency detected")
        if t.get("editorIdentified"):
            lines.append(f"Editor identified in metadata: {t.get('software')}")
        if t.get("hasGps"):
            lines.append("EXIF GPS section present")
    
    # ELA
    if "ela" in sig:
        e = sig["ela"]
        lines.append(f"ELA analysis: mean error {e['meanErrorPct']}%, uniform={e['uniform']}")
    
    return {
        "finding": "; ".join(lines),
        "type": "observed",
        "source": {"name": "Forensic Engine", "url": "internal", "type": "primary", "verified": True},
        "confidence": 90,
        "rationale": "Deterministic analysis of container and re-encoding artifacts.",
    }


if __name__ == "__main__":  # self-check: fails loudly if any layer regresses
    from PIL import Image

    # JPEG: generate, then re-encode and confirm quality/ELA produce values.
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="JPEG", quality=75)
    data = buf.getvalue()
    sig = analyze_image(data)
    assert sig["perceptualHash"], sig
    assert sig["format"] == "JPEG", sig
    assert 1 <= sig.get("estimatedQuality", 0) <= 100, sig
    assert "ela" in sig and sig["ela"]["blockCount"] == 4, sig
    assert sig["ela"]["heatmap"], sig
    assert isinstance(sig["ela"]["elevatedRegions"], list), sig
    d = describe(data)
    assert "MANIPULATION_LAYER" in d and "ELA" in d, d

    # ELA spatial localization: random noise (high re-encode error) confined to
    # the left half of a 64x64 JPEG (2x2 blocks of 32px) must localize to the
    # two left blocks, not the whole frame, and the heatmap must mark them '#'.
    # A wide quality gap (75→30) is required to make the error observable —
    # a real-world scan has the same property, just a smaller delta.
    import random
    rng = random.Random(1)
    mixed = io.BytesIO()
    base = Image.new("L", (64, 64), 200)
    for y in range(64):
        for x in range(32):
            base.putpixel((x, y), rng.randrange(0, 256))
    base.save(mixed, format="JPEG", quality=75)
    ela = error_level_analysis(mixed.getvalue(), reencode_quality=30)
    assert ela is not None and len(ela["elevatedRegions"]) == 1, ela
    r = ela["elevatedRegions"][0]
    assert r["x"] == 0 and r["y"] == 0 and r["width"] == 32 and r["height"] == 64, r
    lines = ela["heatmap"].splitlines()
    assert len(lines) == 2 and all(line[0] == "#" and line[1] == "." for line in lines), ela["heatmap"]

    # PNG: lossless — no ELA, has dHash.
    pbuf = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(pbuf, format="PNG")
    sig2 = analyze_image(pbuf.getvalue())
    assert sig2["format"] == "PNG" and "ela" not in sig2, sig2
    assert sig2.get("perceptualHash"), sig2

    print("image_forensics self-check OK")