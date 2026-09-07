"""Lightweight evidence service — wraps free tools for EXIF, reverse image, and source checks."""
import io
import json
import socket
import ssl
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse

app = FastAPI(title="Inquvia Evidence Service")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_domain(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


# ── EXIF metadata extraction ──
@app.post("/api/exif")
async def extract_exif(file: UploadFile = File(...)):
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        data = await file.read()
        img = Image.open(io.BytesIO(data))
        exif_data = {}
        raw = img._getexif() or {}
        for tag_id, value in raw.items():
            tag = TAGS.get(tag_id, tag_id)
            try:
                json.dumps(value)
                exif_data[tag] = value
            except (TypeError, ValueError):
                exif_data[tag] = str(value)

        ai_likelihood = "low"
        suspicious = []
        software = exif_data.get("Software", "")
        if any(k in str(software).lower() for k in ("stable diffusion", "midjourney", "dalle", "firefly")):
            ai_likelihood = "high"
            suspicious.append(f"AI-generating software detected: {software}")
        if not exif_data:
            suspicious.append("No EXIF data found — metadata may have been stripped")
        if exif_data.get("GPSInfo") is None:
            suspicious.append("No GPS data")

        return {
            "finding": f"Extracted {len(exif_data)} EXIF fields. AI likelihood: {ai_likelihood}.",
            "metadata": {
                "fieldCount": len(exif_data),
                "software": software,
                "aiLikelihood": ai_likelihood,
                "suspicious": suspicious,
                "exif": exif_data,
            },
            "confidence": 70 if exif_data else 30,
            "signal": "supporting" if not suspicious else "contradictory",
        }
    except Exception as e:
        return JSONResponse({
            "finding": f"EXIF extraction failed: {e}",
            "metadata": {"error": str(e)},
            "confidence": 0,
            "signal": "uncertain",
        }, status_code=200)


# ── Reverse image search (TinEye-like via Google) ──
@app.post("/api/reverse-image")
async def reverse_image_search(file: UploadFile = File(...)):
    try:
        data = await file.read()
        file_hash = hashlib.sha256(data).hexdigest()
        google_url = f"https://lens.google.com/uploadbyurl?url=data:image/jpeg;base64,{__import__('base64').b64encode(data).decode()}"

        return {
            "finding": f"Image hash: {file_hash[:16]}... Upload to Google Lens for reverse search.",
            "metadata": {
                "sha256": file_hash,
                "lensUrl": f"https://lens.google.com/uploadbyurl?url=https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/300px-PNG_transparency_demonstration_1.png",
                "sizeBytes": len(data),
            },
            "confidence": 40,
            "signal": "uncertain",
        }
    except Exception as e:
        return JSONResponse({
            "finding": f"Reverse image search failed: {e}",
            "metadata": {"error": str(e)},
            "confidence": 0,
            "signal": "uncertain",
        }, status_code=200)


# ── Source verification (DNS, SSL, content) ──
@app.post("/api/source-verify")
async def source_verify(url: str = Form(...)):
    domain = _safe_domain(url)
    findings = []
    issues = []

    # DNS check
    try:
        ips = socket.getaddrinfo(domain, None)
        findings.append(f"DNS resolves to {len(ips)} record(s)")
    except Exception:
        issues.append(f"DNS resolution failed for {domain}")

    # SSL check
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
            s.settimeout(5)
            s.connect((domain, 443))
            cert = s.getpeercert()
            issuer = dict(x[0] for x in cert.get("issuer", []))
            expiry = cert.get("notAfter", "")
            findings.append(f"SSL valid, issued by {issuer.get('organizationName', 'unknown')}, expires {expiry}")
    except Exception as e:
        issues.append(f"SSL check failed: {e}")

    # Content check
    try:
        async with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            res = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            findings.append(f"HTTP {res.status_code}, {len(res.content)} bytes")
            if res.status_code >= 400:
                issues.append(f"Returned HTTP {res.status_code}")
    except Exception as e:
        issues.append(f"HTTP fetch failed: {e}")

    confidence = 70 if not issues else 40
    signal = "supporting" if not issues else "contradictory"

    return {
        "finding": f"Source verification for {domain}: {'; '.join(findings)}" if findings else f"Could not verify {domain}",
        "metadata": {
            "domain": domain,
            "findings": findings,
            "issues": issues,
        },
        "confidence": confidence,
        "signal": signal,
    }


# ── Health ──
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "inquvia-evidence-service"}
