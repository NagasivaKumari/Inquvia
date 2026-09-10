"""Executable evidence checks (the "services" advertised on the evidence page).

Each planned evidence requirement whose capability maps to a runnable
deterministic check is executed server-side against the user's submission and
recorded as acquired evidence (origin "evidence_service"). Checks that would
require an external provider we don't have (reverse-image indexes, WHOIS,
search engines, transcription) are skipped and simply are not counted.

ponytail: no model calls here — these are reproducible observations; the
analyzer later reasons over them and gives the verdict.
"""
import csv
import io
import json
import logging
import secrets
from datetime import datetime, timezone

from .. import db
from ..libraries import signals as signals_lib
from ..libraries import web_inspector
from ..libraries.analyze import read_stored_text

logger = logging.getLogger(__name__)

CHECK_LABELS = {
    "image_provenance": "Image provenance & metadata analysis",
    "image_metadata": "Image metadata / EXIF inspection",
    "video_analysis": "Video container & encoding analysis",
    "frame_evidence": "Video track & frame structure probe",
    "audio_transcription": "Audio container & metadata analysis",
    "document_verify": "Document text extraction",
    "data_consistency": "Structured data consistency check",
    "content_extract": "URL content inspection",
}

# Which input kind feeds each check.
KIND_FOR_CAP = {
    "image_provenance": "image",
    "image_metadata": "image",
    "video_analysis": "video",
    "frame_evidence": "video",
    "audio_transcription": "audio",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nanoid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)[:8]}"


def _inputs_of(inv: dict, input_type: str) -> list[dict]:
    return [i for i in (inv.get("inputs") or []) if i.get("type") == input_type]


def _media_findings(inv: dict, kind: str) -> list[str]:
    findings = []
    for inp in _inputs_of(inv, kind):
        path = inp.get("filePath")
        if not path:
            continue
        data = signals_lib.load_bytes(path)
        if not data:
            continue
        desc = signals_lib.describe(data, kind)
        if desc:
            findings.append(desc)
    return findings


def _document_findings(inv: dict) -> list[str]:
    findings = []
    for inp in _inputs_of(inv, "document"):
        path = inp.get("filePath")
        if not path:
            continue
        text = read_stored_text(path, 4000)
        label = inp.get("content") or inp.get("fileName") or "document"
        if text and text.strip():
            snippet = text.strip().replace("\n", " ")[:400]
            findings.append(
                f"Document check ({label}): extracted {len(text)} characters of text. "
                f"Start: {snippet}"
            )
        else:
            findings.append(
                f"Document check ({label}): no extractable text layer found (scanned/OCR-required)."
            )
    return findings


def _data_findings(inv: dict) -> list[str]:
    findings = []
    for inp in _inputs_of(inv, "data") or _inputs_of(inv, "json") or _inputs_of(inv, "csv") or _inputs_of(inv, "text"):
        path = inp.get("filePath")
        if not path:
            continue
        text = read_stored_text(path, 200000)
        if not text:
            continue
        label = inp.get("fileName") or "structured data"
        try:
            table = list(csv.reader(io.StringIO(text)))
            if table:
                n_rows = max(0, len(table) - (1 if table and len(table) > 1 else 0))
                header = " | ".join((table[0] or [])[:8])
                missing = sum(1 for row in table[1:] for c in row if not c.strip())
                findings.append(
                    f"Structured data check ({label}): CSV with {n_rows} data rows "
                    f"[columns: {header[:150]}]; {missing} empty cells observed."
                )
                continue
        except Exception:
            pass
        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                findings.append(
                    f"Structured data check ({label}): JSON array of {len(obj)} records."
                )
            elif isinstance(obj, dict):
                findings.append(
                    f"Structured data check ({label}): JSON object with "
                    f"{len(obj)} top-level keys: {list(obj.keys())[:10]}."
                )
            else:
                findings.append(f"Structured data check ({label}): JSON scalar value.")
            continue
        except Exception:
            pass
        findings.append(
            f"Structured data check ({label}): content could not be parsed as CSV or JSON."
        )
    return findings


async def _url_findings(inv: dict) -> list[str]:
    findings = []
    for inp in _inputs_of(inv, "url"):
        url = inp.get("content")
        if not url:
            continue
        inspection = inv.get("webInspection") or await web_inspector.inspect_live_url(url)
        if not inspection:
            findings.append(f"URL check ({url}): could not be inspected.")
            continue
        bits = [
            f"URL check ({url}): HTTP {inspection.get('statusCode') or 'n/a'}",
            f"online={bool(inspection.get('isOnline'))}",
        ]
        if inspection.get("title"):
            bits.append(f"title={inspection['title'][:120]}")
        if inspection.get("sslValid") is not None:
            bits.append(f"sslValid={inspection['sslValid']}")
        if inspection.get("dnsRecords"):
            bits.append(f"dnsIPs={len(inspection['dnsRecords'])}")
        findings.append(", ".join(bits))
    return findings


async def _execute_check(inv: dict, cap: str) -> list[str]:
    if cap in KIND_FOR_CAP:
        return _media_findings(inv, KIND_FOR_CAP[cap])
    if cap == "document_verify":
        return _document_findings(inv)
    if cap == "data_consistency":
        return _data_findings(inv)
    if cap == "content_extract":
        return await _url_findings(inv)
    return []


async def run_evidence_checks(inv: dict) -> dict:
    """Execute runnable planned checks; append evidence + acquisition records."""
    if any(
        (e.get("metadata") or {}).get("origin") == "evidence_service"
        for e in (inv.get("evidence") or [])
    ):
        return inv

    for req in inv.get("evidenceRequirements") or []:
        cap = req.get("capability")
        if cap not in CHECK_LABELS:
            continue
        try:
            findings = await _execute_check(inv, cap)
        except Exception:
            logger.exception("evidence check %s failed", cap)
            continue
        for finding in findings:
            finding = finding[:2000]
            now = _now_iso()
            ev_id = _nanoid("ev")
            ev = {
                "id": ev_id,
                "type": req.get("type") or "evidence",
                "source": f"Inquvia check: {CHECK_LABELS[cap]}",
                "finding": finding,
                "signal": "uncertain",
                "status": "collected",
                "confidence": None,
                "timestamp": now,
                "metadata": {
                    "origin": "evidence_service",
                    "checkCapability": cap,
                },
            }
            inv.setdefault("evidence", []).append(ev)
            inv.setdefault("acquisitions", []).append({
                "id": _nanoid("acq"),
                "investigationId": inv["id"],
                "capability": cap,
                "serviceName": CHECK_LABELS[cap],
                "amountMicro": 0,
                "paymentState": "evidence_received",
                "network": "internal",
                "evidence": {"signal": "uncertain", "finding": finding[0:300], "source": ev["source"]},
                "createdAt": now,
            })

    db.save_investigation(inv)
    return db.get_investigation(inv["id"])