"""Client for the separately deployed Inquvia Evidence Services.

Communicates with Evidence Services exclusively through the HTTP base URL
configured via the EVIDENCE_SERVICE_URL environment variable.
Never hardcodes the URL or accesses local Evidence Services files.
"""
import logging
from typing import Any
import httpx

from .. import config

logger = logging.getLogger(__name__)


def get_base_url() -> str:
    return (config.EVIDENCE_SERVICE_URL or "").rstrip("/")


def is_configured() -> bool:
    return bool(get_base_url())


def _format_evidence_ref(ev: dict) -> dict:
    """Format an evidence dict or raw response into an EvidenceItemRef."""
    ev_id = ev.get("evidence_id") or ev.get("id") or "ev_ref"
    return {
        "evidence_id": ev_id,
        "type": ev.get("type"),
        "text": ev.get("finding") or ev.get("claim"),
        "observations": ev.get("observations") or [],
        "facts": ev.get("facts") or [],
        "sources": ev.get("sources") or [],
        "payload": ev.get("metadata") or ev.get("payload") or ev,
    }


async def acquire_url_evidence(url: str, claim: str | None = None, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/url on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None

    endpoint = f"{base_url}/api/evidence/url"
    payload = {"url": url, "claim": claim or ""}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence URL endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to acquire URL evidence from %s: %s", endpoint, e)
    return None


async def acquire_image_evidence(file_bytes: bytes, filename: str, mime: str, claim: str | None = None, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/image on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None

    endpoint = f"{base_url}/api/evidence/image"
    files = {"file": (filename or "image.jpg", file_bytes, mime or "image/jpeg")}
    data = {"claim": claim or ""}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(endpoint, files=files, data=data, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Image endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to acquire Image evidence from %s: %s", endpoint, e)
    return None


async def acquire_video_evidence(file_bytes: bytes, filename: str, mime: str, claim: str | None = None, max_frames: int = 10, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/video on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None

    endpoint = f"{base_url}/api/evidence/video"
    files = {"file": (filename or "video.mp4", file_bytes, mime or "video/mp4")}
    data = {"claim": claim or "", "max_frames": str(max_frames)}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(endpoint, files=files, data=data, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Video endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to acquire Video evidence from %s: %s", endpoint, e)
    return None


async def acquire_document_evidence(file_bytes: bytes, filename: str, mime: str, claim: str | None = None, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/document on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None

    endpoint = f"{base_url}/api/evidence/document"
    files = {"file": (filename or "document.pdf", file_bytes, mime or "application/pdf")}
    data = {"claim": claim or ""}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            res = await client.post(endpoint, files=files, data=data, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Document endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to acquire Document evidence from %s: %s", endpoint, e)
    return None


async def acquire_structured_evidence(
    file_bytes: bytes | None = None,
    filename: str | None = None,
    mime: str | None = None,
    payload_json: str | None = None,
    claim: str | None = None,
    proof: str | None = None,
) -> dict | None:
    """Call POST /api/evidence/structured on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None

    endpoint = f"{base_url}/api/evidence/structured"
    files = {}
    if file_bytes:
        files["file"] = (filename or "data.csv", file_bytes, mime or "text/csv")
    data = {}
    if claim:
        data["claim"] = claim
    if payload_json:
        data["payload_json"] = payload_json
    headers = {"x-402-proof": proof} if proof else None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(endpoint, files=files or None, data=data or None, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Structured endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to acquire Structured evidence from %s: %s", endpoint, e)
    return None


async def call_cross_modal(evidence_list: list[dict], claim: str | None = None, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/cross-modal on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None

    endpoint = f"{base_url}/api/evidence/cross-modal"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Cross-Modal endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to call cross-modal evidence from %s: %s", endpoint, e)
    return None


async def call_timeline(evidence_list: list[dict], claim: str | None = None, proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/timeline on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None

    endpoint = f"{base_url}/api/evidence/timeline"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Timeline endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to call timeline evidence from %s: %s", endpoint, e)
    return None


async def call_provenance(evidence_list: list[dict], proof: str | None = None) -> dict | None:
    """Call POST /api/evidence/provenance on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or len(evidence_list) < 2:
        return None

    endpoint = f"{base_url}/api/evidence/provenance"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"evidence": formatted}
    headers = {"x-402-proof": proof} if proof else None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(endpoint, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()
            logger.warning("Evidence Provenance endpoint %s returned status %d: %s", endpoint, res.status_code, res.text)
    except Exception as e:
        logger.error("Failed to call provenance evidence from %s: %s", endpoint, e)
    return None

