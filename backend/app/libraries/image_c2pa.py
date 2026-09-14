"""C2PA / Content Credentials manifest detection for images.

Parses observable provenance markers from file bytes and embedded XMP.
Does not verify cryptographic trust chains unless a full C2PA library is present.
"""
from __future__ import annotations

import re


def _extract_xmp_snippet(buf: bytes, limit: int = 8000) -> str:
    for marker in (b"<?xpacket", b"<x:xmpmeta", b"http://ns.adobe.com/xap/1.0/"):
        idx = buf.find(marker)
        if idx >= 0:
            chunk = buf[idx:idx + limit]
            try:
                return chunk.decode("utf-8", errors="ignore")
            except Exception:
                pass
    return ""


def analyze(buf: bytes) -> dict:
    """Detect C2PA / Content Credentials presence and extract observable fields."""
    result = {
        "c2paBytesPresent": False,
        "jumbPresent": False,
        "contentCredentialsMentioned": False,
        "manifestMarkers": [],
        "xmpFields": {},
        "credentialsPresent": False,
        "validationStatus": "not_validated",
        "disclaimer": (
            "Marker presence does not prove authenticity. Missing credentials does not "
            "prove an image is fake. Cryptographic validation requires a full C2PA verifier."
        ),
    }

    lower = buf.lower()
    if b"c2pa" in lower:
        result["c2paBytesPresent"] = True
        result["manifestMarkers"].append("c2pa_string_in_file")
    if b"jumb" in lower:
        result["jumbPresent"] = True
        result["manifestMarkers"].append("jumb_box_or_chunk")
    if b"contentcredentials" in lower or b"content credentials" in lower:
        result["contentCredentialsMentioned"] = True
        result["manifestMarkers"].append("content_credentials_reference")

    xmp = _extract_xmp_snippet(buf)
    if xmp:
        for tag in ("dc:creator", "photoshop:Credit", "xmpMM:History", "c2pa", "claim_generator"):
            if tag.lower() in xmp.lower():
                m = re.search(rf"{re.escape(tag)}[^<]{{0,200}}", xmp, re.I)
                if m:
                    result["xmpFields"][tag] = m.group(0)[:300]

    result["credentialsPresent"] = bool(
        result["c2paBytesPresent"] or result["jumbPresent"] or result["contentCredentialsMentioned"]
        or result["xmpFields"]
    )

    # Optional full library validation.
    try:
        import c2pa  # type: ignore  # noqa: F401
        result["validationStatus"] = "library_available_not_invoked"
    except ImportError:
        pass

    return result


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = ["C2PA / CONTENT CREDENTIALS (observed markers):"]
    if result.get("credentialsPresent"):
        lines.append("- Content Credentials or C2PA markers detected in file")
        for m in result.get("manifestMarkers") or []:
            lines.append(f"- marker: {m}")
        for k, v in (result.get("xmpFields") or {}).items():
            lines.append(f"- XMP {k}: {v[:120]}")
    else:
        lines.append("- No C2PA / Content Credentials markers detected")
    lines.append(f"- validation: {result.get('validationStatus')}")
    lines.append(f"- note: {result.get('disclaimer')}")
    return "\n".join(lines)
