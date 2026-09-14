"""Queryable persistence for image-investigation analyses.

Denormalizes every image-check result into one document per (investigation,
image) in the `image_analyses` collection so production can filter/aggregate
across all the verticals at once: privacy/PII, safety, document, commercial,
scientific, geospatial, quality, watermark/logo, AI/C2PA, accessibility, meme,
reverse-search provenance, and batch comparisons.

Constructor data comes from two places already attached to the investigation:
- the input record caches (``inp["privacyScan"]``, ``inp["imageQuality"]`` ...)
  which hold the structured analysis payloads keyed correctly per image, and
- the ``evidence`` records which hold the human-readable finding + signal.

Everything here is derived from already-persisted observations; nothing new is
computed and nothing is invented when a check did not run.
"""
from __future__ import annotations

from .. import db

# Per-image capabilities: input-cache key on the image input record.
_PER_IMAGE_INPUT_KEYS = {
    "image_visual_observation": "visualObservation",
    "image_manipulation": "imageForensics",
    "image_reverse_search": "reverseImage",
    "image_ocr": "imageOcr",
    "ai_detection": "aiDetection",
    "image_c2pa": "c2pa",
    "pii_detection": "privacyScan",
    "safety_analysis": "safetyAnalysis",
    "image_quality": "imageQuality",
    "document_analysis": "documentAnalysis",
    "meme_context": "memeTimeline",
    "logo_watermark": "logoObs",
    "geospatial_analysis": "geoObs",
    "accessibility_description": "accessibilityDescription",
    "commercial_verification": "commercialObs",
    "scientific_technical": "scientificObs",
}

# Investigation-level capabilities (not per-image) — copied onto each doc.
# batch/investigation imageComparison are big, so they attach to index 0 only.
_INV_LEVEL_KEYS = {
    "image_authoritative_search": "authoritativeSearch",
    "copyright_attribution": None,  # derived: no input cache, from evidence metadata
}
_LARGE_INV_LEVEL_KEYS = {"batch_investigation": "batchAnalysis", "image_compare": "imageComparison",
                         "before_after_analysis": "imageComparison"}

IMAGE_CAPS = set(_PER_IMAGE_INPUT_KEYS) | set(_INV_LEVEL_KEYS) | set(_LARGE_INV_LEVEL_KEYS)


def _evidence_by_cap(inv: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for ev in inv.get("evidence") or []:
        meta = ev.get("metadata") or {}
        cap = meta.get("checkCapability")
        if cap and cap in IMAGE_CAPS:
            out.setdefault(cap, []).append(ev)
    return out


def _evidence_for_file(records: list[dict], file_name: str) -> dict | None:
    for ev in records:
        meta = ev.get("metadata") or {}
        if meta.get("fileName") == file_name:
            return ev
    return None


def _flags(result_by_cap: dict[str, dict]) -> dict:
    """Queryable one-hot flags per image, derived only from observed results."""
    f: dict[str, bool] = {}

    def _r(cap: str) -> dict:
        return (result_by_cap.get(cap) or {}).get("result") or {}

    pii = _r("pii_detection")
    if pii.get("sensitiveContentDetected"):
        f["privacy_sensitive"] = True
    faces = pii.get("faces") or {}
    if faces.get("faceCount"):
        f["privacy_faces"] = True
    codes = pii.get("barcodes") or {}
    if codes.get("codeCount"):
        f["privacy_scan_codes"] = True
    if pii.get("textPii"):
        f["privacy_text_pii"] = True

    safety = _r("safety_analysis")
    if safety.get("severity") in ("low", "medium", "high"):
        f["safety_hazard"] = True

    doc = _r("document_analysis")
    if doc.get("likelyDocumentImage"):
        f["document_like"] = True

    comm = _r("commercial_verification")
    if comm.get("verdict") == "likely_counterfeit":
        f["commercial_counterfeit"] = True
    elif comm.get("suspicious"):
        f["commercial_suspicious"] = True

    sci = _r("scientific_technical")
    if sci.get("category") in ("chart", "diagram", "lab", "engineering"):
        f["scientific_technical"] = True

    geo = _r("geospatial_analysis")
    if geo.get("isGeographic"):
        f["geospatial"] = True

    q = _r("image_quality")
    blur = q.get("blur") or {}
    if blur.get("sharpnessBand") == "likely_blurry":
        f["quality_blurry"] = True
    if q.get("resolutionBand") in ("very_low", "low"):
        f["quality_low_resolution"] = True
    if q.get("recompression"):
        f["quality_recompressed"] = True

    ai = _r("ai_detection")
    band = ai.get("indicatorBand")
    mband = (ai.get("modelAssessment") or {}).get("band")
    if band in ("possible_ai_indicators", "weak_ai_indicators") or mband in ("likely_ai", "possible_ai"):
        f["ai_synthetic_indicators"] = True

    c2pa = _r("image_c2pa")
    if c2pa.get("credentialsPresent"):
        f["c2pa_credentials"] = True

    logo = _r("logo_watermark")
    if any(logo.get(k) for k in ("logos", "watermarks", "seals")) or logo.get("tamperSigns"):
        f["logo_watermark"] = True

    acc = _r("accessibility_description")
    if acc.get("altText"):
        f["accessibility_alt"] = True

    vis = _r("image_visual_observation")
    if vis.get("description"):
        f["visually_read"] = True

    return f


def _image_analysis_docs(inv: dict) -> list[dict]:
    images = [i for i in (inv.get("inputs") or []) if i.get("type") == "image"]
    if not images:
        return []

    ev_by_cap = _evidence_by_cap(inv)

    # Investigation-level payloads copied onto docs.
    inv_level: dict[str, dict] = {}
    auth = images[0].get("authoritativeSearch")
    if auth:
        inv_level["image_authoritative_search"] = auth
    for ev in ev_by_cap.get("copyright_attribution") or []:
        clue = (ev.get("metadata") or {}).get("copyrightClues")
        if clue:
            inv_level["copyright_attribution"] = {
                "signal": ev.get("signal"), "finding": ev.get("finding"),
                "copyrightClues": clue,
            }
    for cap, key in _LARGE_INV_LEVEL_KEYS.items():
        payload = inv.get(key)
        if payload:
            ev = (ev_by_cap.get(cap) or [{}])[0]
            inv_level[cap] = {"signal": ev.get("signal"), "finding": ev.get("finding"),
                              "result": payload}

    docs = []
    for idx, img in enumerate(images):
        file_name = img.get("fileName")
        checks: dict[str, dict] = {}
        for cap, cache_key in _PER_IMAGE_INPUT_KEYS.items():
            payload = img.get(cache_key)
            if not payload:
                continue  # check did not run for this image — nothing observed
            ev = _evidence_for_file(ev_by_cap.get(cap) or [], file_name) or {}
            checks[cap] = {
                "name": _cap_name(cap),
                "signal": ev.get("signal") or "observed",
                "finding": (ev.get("finding") or "")[:2000],
                "result": payload,
            }

        doc = {
            "_id": f"{inv['id']}:{idx}",
            "investigationId": inv["id"],
            "userId": inv.get("userId"),
            "capability": inv.get("capability"),
            "question": (inv.get("question") or "")[:500],
            "createdAt": inv.get("updatedAt") or inv.get("createdAt"),
            "image": {
                "index": idx,
                "fileName": file_name,
                "mimeType": img.get("mimeType"),
                "filePath": img.get("filePath"),
            },
            "checks": checks,
            "flags": _flags(checks),
        }
        # Large comparative payloads on the first image doc only.
        if idx == 0:
            first_only = {}
            for cap, payload in inv_level.items():
                first_only[cap] = payload
            if first_only:
                doc["investigationLevel"] = first_only
        docs.append(doc)
    return docs


_CAP_NAMES = None


def _cap_name(cap: str) -> str:
    global _CAP_NAMES
    if _CAP_NAMES is None:
        try:
            from ..libraries.evidence_checks import CHECK_LABELS
            _CAP_NAMES = CHECK_LABELS
        except Exception:
            _CAP_NAMES = {}
    return _CAP_NAMES.get(cap, cap.replace("_", " "))


def persist(inv: dict) -> int:
    """Write (investigation × image) analysis documents. Returns count written."""
    docs = _image_analysis_docs(inv)
    if not docs:
        return 0
    for doc in docs:
        db.replace_image_analysis(doc)
    return len(docs)


def list_for_user(user_id: str, *, limit: int = 50, cap: str = "", flag: str = "",
                  investigation_id: str = ""):
    return db.list_image_analyses(
        user_id, limit=limit, cap=cap, flag=flag, investigation_id=investigation_id
    )


if __name__ == "__main__":  # self-check: mapping + flags are order-stable
    inv = {
        "id": "inv_test", "userId": "u1", "capability": "image-investigation",
        "question": "any question", "createdAt": "2026-01-01T00:00:00+00:00",
        "inputs": [
            {"type": "image", "fileName": "a.jpg", "mimeType": "image/jpeg",
             "imageQuality": {"resolutionBand": "very_low", "blur": {"sharpnessBand": "likely_blurry"}},
             "privacyScan": {"sensitiveContentDetected": True, "faces": {"faceCount": 2},
                             "barcodes": {"codeCount": 0}, "textPii": {}},
             "imageForensics": {"format": "JPEG"}},
            {"type": "image", "fileName": "b.jpg", "mimeType": "image/jpeg",
             "imageQuality": {"resolutionBand": "high", "blur": {"sharpnessBand": "likely_sharp"}},
             "privacyScan": {"sensitiveContentDetected": False, "faces": {"faceCount": 0},
                             "barcodes": {"codeCount": 0}, "textPii": {}},
             "imageForensics": {"format": "JPEG"}},
        ],
        "evidence": [
            {"signal": "observed", "finding": "a_finding", "metadata": {
                "checkCapability": "image_quality", "fileName": "a.jpg"}},
        ],
        "batchAnalysis": {"duplicateClusterCount": 0},
    }
    docs = _image_analysis_docs(inv)
    assert len(docs) == 2, len(docs)
    assert docs[0]["_id"] == "inv_test:0" and docs[1]["_id"] == "inv_test:1"
    assert docs[0]["flags"]["privacy_faces"] and docs[0]["flags"]["quality_blurry"]
    assert "privacy_faces" not in docs[1]["flags"]
    assert docs[0]["checks"]["image_quality"]["finding"] == "a_finding"
    assert docs[1]["checks"]["image_quality"]["finding"] == ""
    assert docs[0]["investigationLevel"]["batch_investigation"]["result"] is not None
    assert "investigationLevel" not in docs[1]
    assert _image_analysis_docs({"id": "x", "inputs": [], "evidence": []}) == []
    print("image_analytics self-check OK")