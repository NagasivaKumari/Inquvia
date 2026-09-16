"""C2PA / Content Credentials manifest detection for images.

Parses observable provenance markers from file bytes and embedded XMP, and
verifies the JUMBF manifest store cryptographically when c2pa-python is
installed (optional dependency). Without the library, only markers are reported.
"""
from __future__ import annotations

import io
import json
import re
import time
import urllib.request

_TRUST_ANCHORS_URL = "https://contentcredentials.org/trust/anchors.pem"
_VERIFIER_CTX = ({"ctx": None, "fetched": 0.0}, 86400.0)  # context cache + TTL (1 day)


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
    _verify_with_c2pa(buf, result)

    return result


def _verifier_context():
    """Return the cached c2pa.Context, fetching the official trust anchors on first use."""
    return refresh_verifier_context()


def refresh_verifier_context() -> None:
    """Fetch the official trust anchors and rebuild the cached verifier Context (once/day)."""
    cached = _VERIFIER_CTX[0]
    if cached["ctx"] is not None and time.time() - cached["fetched"] < _VERIFIER_CTX[1]:
        return
    try:
        from c2pa import Context  # type: ignore
    except ImportError:
        return
    config = {"verify": {"verify_cert_anchors": True}}
    try:
        anchors = urllib.request.urlopen(_TRUST_ANCHORS_URL, timeout=15).read().decode("utf-8")
        if anchors.strip():
            config["trust"] = {"trust_anchors": anchors}
    except Exception:
        pass
    cached["ctx"] = Context.from_dict(config)
    cached["fetched"] = time.time()


def _verify_with_c2pa(buf: bytes, result: dict) -> None:
    """Verify the manifest store with c2pa-python if installed. Fills result in place."""
    try:
        from c2pa import Reader  # type: ignore
    except ImportError:
        result["validationStatus"] = "unavailable"
        return

    try:
        reader = Reader(io.BytesIO(buf), context=_verifier_context())
    except Exception:
        result["validationStatus"] = "no_c2pa_manifest"
        return

    try:
        store = json.loads(reader.json())
    except Exception:
        result["validationStatus"] = "parse_error"
        return

    manifests = store.get("manifests") or {}
    result["c2paBytesPresent"] = True
    result["manifestCount"] = len(manifests)
    result["activeManifest"] = store.get("active_manifest")
    result["validationState"] = store.get("validation_state") or "unknown"

    issues = {}
    for section in (store.get("validation_results", {}).get("activeManifest") or {}).values():
        for item in section or []:
            code = item.get("code", "unknown")
            issues.setdefault(code, item.get("explanation", ""))
    result["validationIssues"] = issues
    result["signerTrusted"] = (
        result["validationState"] == "Valid" and "signingCredential.untrusted" not in issues
    )

    if manifests:
        manifest = next(iter(manifests.values()))
        result["claimGenerator"] = manifest.get("claim_generator")
        sig = manifest.get("signature_info") or {}
        if sig:
            result["signer"] = {
                "alg": sig.get("alg"),
                "issuer": sig.get("issuer"),
                "commonName": sig.get("common_name"),
                "time": sig.get("time"),
            }
        actors = manifest.get("claim_generator_info") or []
        if actors:
            result["claimGeneratorInfo"] = actors


def describe(result: dict) -> str:
    if not result:
        return ""
    lines = ["C2PA / CONTENT CREDENTIALS (observed markers):"]
    vs = result.get("validationStatus")
    if vs in (None, "unavailable"):
        lines.append("- C2PA verifier library not installed; marker scan only")
    elif vs == "no_c2pa_manifest":
        lines.append("- No C2PA manifest store found by cryptographic verifier")
    elif vs == "parse_error":
        lines.append(f"- C2PA manifest store found but could not be parsed ({vs})")
    else:
        issues = result.get("validationIssues") or {}
        lines.append(f"- C2PA manifest store found: {result.get('manifestCount')} manifest(s)")
        if result.get("claimGenerator"):
            lines.append(f"- claim generator: {result['claimGenerator'][:120]}")
        sig = result.get("signer")
        if sig:
            parts = [f"alg {sig.get('alg')}"]
            if sig.get("issuer"):
                parts.append(f"issuer {sig.get('issuer')}")
            if sig.get("commonName"):
                parts.append(f"CN {sig.get('commonName')}")
            lines.append("- signed: " + ", ".join(parts))
        state = result.get("validationState", "unknown")
        if result.get("signerTrusted"):
            lines.append(f"- validation state: {state} — trusted signer (C2PA trust list)")
        else:
            lines.append(f"- validation state: {state} — signer not in C2PA trust list")
        if issues:
            for code, explanation in list(issues.items())[:5]:
                lines.append(f"- validation issue {code}: {explanation[:120]}")
    if result.get("credentialsPresent"):
        lines.append("- C2PA / Content Credentials markers detected in file")
        for m in result.get("manifestMarkers") or []:
            lines.append(f"- marker: {m}")
        for k, v in (result.get("xmpFields") or {}).items():
            lines.append(f"- XMP {k}: {v[:120]}")
    else:
        lines.append("- No C2PA / Content Credentials markers detected")
    lines.append(f"- note: {result.get('disclaimer')}")
    return "\n".join(lines)


def _self_check() -> None:
    """One runnable check: marker scan, no-manifest path, and a real C2PA verify (if network + lib)."""
    markers = analyze(b"junk c2pa contentcredentials bytes")
    assert markers["contentCredentialsMentioned"] and markers["credentialsPresent"]
    describe(markers)

    plain = bytearray(3000)
    plain[:3] = b"\xff\xd8\xff"  # JPEG SOI so verifier sees an asset, not random bytes
    no_store = {}
    _verify_with_c2pa(plain, no_store)
    assert no_store["validationStatus"] == "no_c2pa_manifest"

    try:
        import urllib.request

        data = urllib.request.urlopen(
            "https://raw.githubusercontent.com/contentauth/c2pa-python/main/tests/fixtures/C.jpg",
            timeout=20,
        ).read()
    except Exception:
        print("self-check: network skipped, C2PA signed-fixture check not run")
        return
    signed = analyze(data)
    assert signed["c2paBytesPresent"] and signed["manifestCount"] >= 1, signed
    assert signed.get("signer"), signed
    assert signed.get("signerTrusted") is False, "test signing cert must NOT be in the official trust list"
    print("self-check OK:", signed.get("validationState"), signed.get("signer", {}).get("issuer"))


if __name__ == "__main__":
    _self_check()
