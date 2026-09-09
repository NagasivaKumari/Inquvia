"""Client for the separately deployed Inquvia Evidence Services.

Communicates with Evidence Services exclusively through the HTTP base URL
configured via the EVIDENCE_SERVICE_URL environment variable.
Never hardcodes the URL or accesses local Evidence Services files.

Handles x402 payment requirements from Evidence Services: when a call
returns 402 PAYMENT-REQUIRED, the client probes the provider for payment
details, pays via the server wallet through the GoPlausible facilitator,
and retries with the payment proof.
"""
import asyncio
import base64
import json
import logging
from typing import Any
import httpx

from .. import config

logger = logging.getLogger(__name__)

EVIDENCE_TIMEOUT = 120.0  # generous: hosting cold starts can exceed 60s

# ponytail: test-only injection point for a simulated 402 provider.
_TEST_TRANSPORT = None


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
        "independent": ev.get("independent"),
    }


# ── 402 Challenge Parsing ────────────────────────────────────────────


def _parse_402_challenge(res: httpx.Response) -> dict | None:
    """Parse the x402 PAYMENT-REQUIRED response for payment requirements.

    Checks the payment-required header (base64 or raw JSON) and the response
    body for a payment challenge. Returns None if no parseable challenge.
    """
    header = res.headers.get("payment-required") or res.headers.get("PAYMENT-REQUIRED")
    if header:
        try:
            data = json.loads(base64.b64decode(header).decode("utf-8"))
        except Exception:
            try:
                data = json.loads(header)
            except Exception:
                data = None
        if data:
            accepts = data.get("accepts") or []
            if accepts:
                acc = accepts[0] if isinstance(accepts, list) else accepts
                pay_to = acc.get("payTo") or acc.get("pay_to")
                amount = acc.get("amount")
                if pay_to and amount:
                    try:
                        amount_micro = int(round(float(amount))) if float(amount) < 1e6 else int(amount)
                    except (TypeError, ValueError):
                        amount_micro = 0
                    return {
                        "payTo": pay_to,
                        "amountMicro": amount_micro,
                        "assetId": str(acc.get("asset") or acc.get("assetId") or config.ALGORAND_USDC_ASA),
                        "network": acc.get("network") or data.get("network") or config.ALGORAND_NETWORK_CAIP2,
                        "scheme": acc.get("scheme", "exact"),
                        "resourceUrl": data.get("resourceUrl") or "",
                        "requirement": acc,
                        "resource": data.get("resource") if isinstance(data.get("resource"), dict) else None,
                    }
    # Try the response body as a fallback
    try:
        body = res.json()
        if "accepts" in body or "payTo" in body:
            accepts = body.get("accepts") or []
            if accepts:
                acc = accepts[0] if isinstance(accepts, list) else accepts
                pay_to = acc.get("payTo") or acc.get("pay_to")
                amount = acc.get("amount")
                if pay_to and amount:
                    try:
                        amount_micro = int(round(float(amount))) if float(amount) < 1e6 else int(amount)
                    except (TypeError, ValueError):
                        amount_micro = 0
                    return {
                        "payTo": pay_to,
                        "amountMicro": amount_micro,
                        "assetId": str(acc.get("asset") or config.ALGORAND_USDC_ASA),
                        "network": acc.get("network") or config.ALGORAND_NETWORK_CAIP2,
                        "scheme": acc.get("scheme", "exact"),
                        "resourceUrl": body.get("resourceUrl") or "",
                        "requirement": acc,
                        "resource": body.get("resource") if isinstance(body.get("resource"), dict) else None,
                    }
    except Exception:
        pass
    return None


def _extract_settlement_tx_id(headers: dict) -> str:
    """Extract the settlement transaction ID from response headers."""
    lower = {str(k).lower(): v for k, v in headers.items()}
    for name in ("payment-response", "x-payment-response", "x-x402-payment", "payment-signature"):
        header = lower.get(name)
        if not header:
            continue
        try:
            decoded = json.loads(base64.b64decode(header).decode("utf-8"))
            tx = decoded.get("transaction") or decoded.get("settleTxnId") or decoded.get("txId") or decoded.get("transactionId")
            if isinstance(tx, dict):
                tx = tx.get("txId") or tx.get("hash")
            if tx:
                return str(tx)
        except Exception:
            try:
                parsed = json.loads(header)
                tx = parsed.get("settleTxnId") or parsed.get("txId") or parsed.get("transactionId")
                if tx:
                    return str(tx)
            except Exception:
                continue
    return ""


# ── Core POST with x402 handling ─────────────────────────────────────


async def _post(url: str, *, json_body=None, files=None, data=None,
                headers=None, budget_ctx: dict | None = None) -> dict | None:
    """POST to an Evidence Services endpoint.

    Handles the full x402 flow:
    1. Send request (with any existing proof header)
    2. If 402 → parse challenge → pay via server wallet → retry with proof
    3. Record payment info in the response for budget tracking

    budget_ctx: optional dict with user's budget info for enforcement.
    Returns the response body dict, or None on failure.
    """
    from .downstream import is_available as downstream_available
    from . import downstream

    last = None
    proof_sent = False
    pending_payment = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=EVIDENCE_TIMEOUT, transport=_TEST_TRANSPORT) as client:
                res = await client.post(url, json=json_body, files=files,
                                        data=data, headers=headers or {})

            # Success — return immediately with any payment info attached
            if res.status_code == 200:
                body = res.json()
                # Attach payment info from response headers if present
                settle_tx = _extract_settlement_tx_id(dict(res.headers))
                payment = None
                if settle_tx:
                    payment = {"settlementRef": settle_tx, "status": "settled"}
                elif pending_payment:
                    # No explicit settlement header on retry; use the one we paid for
                    payment = dict(pending_payment)
                    payment["status"] = "settled"
                if payment:
                    body["_payment"] = payment
                return body

            # 402 PAYMENT-REQUIRED — attempt downstream payment
            if res.status_code == 402 and not proof_sent and downstream_available():
                challenge = _parse_402_challenge(res)
                if challenge and challenge["amountMicro"] > 0:
                    # Enforce budget if context provided
                    if budget_ctx:
                        from .budget import enforce_budget
                        decision = enforce_budget(challenge["amountMicro"], budget_ctx)
                        if not decision["allowed"]:
                            logger.warning("Evidence call blocked by budget: %s", decision.get("reason"))
                            return None

                    # Pay the evidence service via server wallet
                    resource_url = challenge.get("resourceUrl") or url
                    pay_result = downstream.pay_and_get_proof(
                        resource_url=resource_url,
                        pay_to=challenge["payTo"],
                        amount_micro=challenge["amountMicro"],
                        asset_id=challenge.get("assetId"),
                        network=challenge.get("network"),
                        requirement=challenge.get("requirement"),
                        resource=challenge.get("resource"),
                    )
                    if pay_result.get("ok"):
                        # Retry with the V2 payment signature header
                        retry_headers = dict(headers or {})
                        retry_headers["PAYMENT-SIGNATURE"] = pay_result["proof"]
                        headers = retry_headers
                        proof_sent = True
                        # Store payment info for later recording on the 200 retry
                        pending_payment = {
                            "settlementRef": pay_result.get("settleTxnId", ""),
                            "amountMicro": challenge["amountMicro"],
                            "payTo": challenge["payTo"],
                            "network": challenge.get("network", ""),
                            "assetId": challenge.get("assetId", ""),
                        }
                        continue
                    else:
                        logger.error("Downstream payment failed: %s", pay_result.get("error"))
                        return None

            last = res

        except Exception as e:
            last = e
            logger.error("Evidence call failed for %s: %s", url, e)

        if attempt == 0:
            await asyncio.sleep(2)

    if isinstance(last, Exception):
        logger.error("Evidence call failed for %s: %s", url, last)
    elif last is not None:
        logger.warning("Evidence endpoint %s returned status %d: %s", url, last.status_code, last.text[:200])
    return None


# ── Provider Discovery (/api/services) ───────────────────────────────


async def discover_remote_services() -> list[dict]:
    """Discover available evidence services and their prices from the
    provider's /api/services endpoint.

    Returns a list of service descriptors (id/name/type/price/etc.), or an
    empty list if the provider is unreachable or doesn't expose the endpoint.
    """
    base_url = get_base_url()
    if not base_url:
        return []
    endpoint = f"{base_url}/api/services"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(endpoint)
        if res.status_code != 200:
            logger.warning("Evidence /api/services returned %d", res.status_code)
            return []
        data = res.json()
        services = data.get("services") if isinstance(data, dict) else None
        if services is None and isinstance(data, list):
            services = data
        if not isinstance(services, list):
            services = []
        # Normalize each service descriptor
        normalized = []
        for s in services:
            if not isinstance(s, dict):
                continue
            svc_id = s.get("id") or s.get("name") or ""
            svc_type = s.get("type") or s.get("service") or ""
            # Fall back to the endpoint path last segment, e.g. /api/evidence/image -> image
            endpoint = s.get("endpoint") or ""
            _, _, tail = endpoint.rpartition("/api/evidence/")
            if not svc_type and tail:
                svc_type = tail
            if not svc_id and not svc_type:
                continue
            normalized.append({
                "id": svc_id or svc_type,
                "type": svc_type or svc_id,
                "name": s.get("name") or svc_type or svc_id,
                "description": s.get("description") or s.get("summary") or "",
                "priceMicro": s.get("priceMicro") or _price_to_micro(
                    s.get("price") if s.get("price") is not None else s.get("price_usdc")),
                "assetId": s.get("assetId") or s.get("asa_id") or config.ALGORAND_USDC_ASA,
                "network": (s.get("network")
                            or (f"algorand:{s['network']}" if s.get("network") and ":" not in str(s.get("network")) else "")
                            or config.ALGORAND_NETWORK_CAIP2),
                "resourceUrl": s.get("resourceUrl") or s.get("url") or base_url,
                "capability": s.get("capability") or "",
                "capabilities": s.get("capabilities") or [
                    c_ for c_ in [s.get("capability"), s.get("type"), svc_type, svc_id] if c_],
                "paid": bool(s.get("paid", s.get("price_usdc") is not None)),
            })
        return normalized
    except Exception as e:
        logger.warning("Evidence /api/services discovery failed: %s", e)
        return []


def _price_to_micro(price) -> int:
    """Convert a whole-USDC price or micro amount to micro-USDC."""
    if price is None:
        return 0
    try:
        f = float(price)
    except (TypeError, ValueError):
        return 0
    # x402 amounts are micro in the common case (>= 1e6); whole-USDC otherwise
    if f >= 1e6:
        return int(f)
    return int(round(f * config.ALGORAND_USDC_DECIMALS))


# ── Evidence Service Endpoints ────────────────────────────────────────


async def acquire_url_evidence(url: str, claim: str | None = None,
                               proof: str | None = None,
                               budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/url on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None
    endpoint = f"{base_url}/api/evidence/url"
    payload = {"url": url, "claim": claim or ""}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def acquire_image_evidence(file_bytes: bytes, filename: str, mime: str,
                                 claim: str | None = None, proof: str | None = None,
                                 budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/image on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None
    endpoint = f"{base_url}/api/evidence/image"
    files = {"file": (filename or "image.jpg", file_bytes, mime or "image/jpeg")}
    data = {"claim": claim or ""}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, files=files, data=data, headers=hdrs, budget_ctx=budget_ctx)


async def acquire_video_evidence(file_bytes: bytes, filename: str, mime: str,
                                 claim: str | None = None, max_frames: int = 10,
                                 proof: str | None = None,
                                 budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/video on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None
    endpoint = f"{base_url}/api/evidence/video"
    files = {"file": (filename or "video.mp4", file_bytes, mime or "video/mp4")}
    data = {"claim": claim or "", "max_frames": str(max_frames)}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, files=files, data=data, headers=hdrs, budget_ctx=budget_ctx)


async def acquire_document_evidence(file_bytes: bytes, filename: str, mime: str,
                                    claim: str | None = None, proof: str | None = None,
                                    budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/document on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None
    endpoint = f"{base_url}/api/evidence/document"
    files = {"file": (filename or "document.pdf", file_bytes, mime or "application/pdf")}
    data = {"claim": claim or ""}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, files=files, data=data, headers=hdrs, budget_ctx=budget_ctx)


async def acquire_structured_evidence(
    file_bytes: bytes | None = None,
    filename: str | None = None,
    mime: str | None = None,
    payload_json: str | None = None,
    claim: str | None = None,
    proof: str | None = None,
    budget_ctx: dict | None = None,
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
    if not payload_json and not file_bytes:
        payload_json = json.dumps({"claim": claim or "Evidence query"})
    if payload_json:
        raw_p = payload_json.strip()
        if not raw_p.startswith("{"):
            raw_p = json.dumps({"query": raw_p})
        data["payload"] = raw_p
        data["payload_json"] = raw_p
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, files=files or None, data=data or None,
                       headers=hdrs, budget_ctx=budget_ctx)


async def call_cross_modal(evidence_list: list[dict], claim: str | None = None,
                           proof: str | None = None,
                           budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/cross-modal on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None
    endpoint = f"{base_url}/api/evidence/cross-modal"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def call_timeline(evidence_list: list[dict], claim: str | None = None,
                        proof: str | None = None,
                        budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/timeline on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None
    endpoint = f"{base_url}/api/evidence/timeline"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def call_provenance(evidence_list: list[dict],
                          proof: str | None = None,
                          budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/provenance on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or len(evidence_list) < 2:
        return None
    endpoint = f"{base_url}/api/evidence/provenance"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def acquire_audio_evidence(file_bytes: bytes, filename: str, mime: str,
                                 claim: str | None = None, proof: str | None = None,
                                 budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/audio on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url:
        return None
    endpoint = f"{base_url}/api/evidence/audio"
    files = {"file": (filename or "audio.mp3", file_bytes, mime or "audio/mpeg")}
    data = {"claim": claim or ""}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, files=files, data=data, headers=hdrs, budget_ctx=budget_ctx)


async def call_assess(evidence_list: list[dict], claim: str | None = None,
                      proof: str | None = None,
                      budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/assess on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None
    endpoint = f"{base_url}/api/evidence/assess"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def call_contradictions(evidence_list: list[dict], claim: str | None = None,
                              proof: str | None = None,
                              budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/contradictions on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or len(evidence_list) < 2:
        return None
    endpoint = f"{base_url}/api/evidence/contradictions"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def call_duplicates(evidence_list: list[dict], claim: str | None = None,
                          proof: str | None = None,
                          budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/duplicates on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or len(evidence_list) < 2:
        return None
    endpoint = f"{base_url}/api/evidence/duplicates"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


async def call_authenticity(evidence_list: list[dict], claim: str | None = None,
                            proof: str | None = None,
                            budget_ctx: dict | None = None,
                            file_bytes: bytes | None = None,
                            filename: str | None = None,
                            mime: str | None = None) -> dict | None:
    """Call POST /api/evidence/authenticity on the deployed Evidence Service.

    The provider's authenticity endpoint validates a raw uploaded artifact
    (multipart 'file'), not evidence references. Without the raw file bytes
    there is nothing to validate, so the call is skipped (no payment).
    """
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None
    endpoint = f"{base_url}/api/evidence/authenticity"
    hdrs = {"x-402-proof": proof} if proof else None
    if not file_bytes:
        logger.info("Authenticity requires a raw evidence file; none available, skipping")
        return None
    return await _post(endpoint,
                       files={"file": (filename or "evidence.bin", file_bytes,
                                       mime or "application/octet-stream")},
                       data={"claim": claim or ""},
                       headers=hdrs, budget_ctx=budget_ctx)


async def call_gaps(evidence_list: list[dict], claim: str | None = None,
                    proof: str | None = None,
                    budget_ctx: dict | None = None) -> dict | None:
    """Call POST /api/evidence/gaps on the deployed Evidence Service."""
    base_url = get_base_url()
    if not base_url or not evidence_list:
        return None
    endpoint = f"{base_url}/api/evidence/gaps"
    formatted = [_format_evidence_ref(e) for e in evidence_list]
    payload = {"claim": claim or "", "evidence": formatted}
    hdrs = {"x-402-proof": proof} if proof else None
    return await _post(endpoint, json_body=payload, headers=hdrs, budget_ctx=budget_ctx)


# ── Self-check (no network) ─────────────────────────────────────────


def _demo():
    """Verify 402 challenge parsing + settlement tx extraction (pure logic)."""
    import httpx as _httpx

    # 1. Header-based challenge (base64 JSON)
    challenge = {
        "x402Version": 2,
        "accepts": [{
            "scheme": "exact",
            "network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
            "payTo": "PAYTOADDR",
            "asset": "10458941",
            "amount": "7500",
        }],
    }
    encoded = base64.b64encode(json.dumps(challenge).encode()).decode()
    res = _httpx.Response(402, headers={"payment-required": encoded})
    parsed = _parse_402_challenge(res)
    assert parsed, "header challenge should parse"
    assert parsed["payTo"] == "PAYTOADDR"
    assert parsed["amountMicro"] == 7500
    assert parsed["requirement"] == challenge["accepts"][0], "requirement must pass through verbatim"

    # 2. Body-based challenge
    body_res = _httpx.Response(402, json={"accepts": [{"scheme": "exact", "payTo": "BODYADDR", "amount": "5000"}]})
    parsed_body = _parse_402_challenge(body_res)
    assert parsed_body and parsed_body["payTo"] == "BODYADDR" and parsed_body["amountMicro"] == 5000

    # 3. No challenge -> None
    empty = _httpx.Response(402)
    assert _parse_402_challenge(empty) is None

    # 4. Settlement tx extraction from PAYMENT-RESPONSE (V2 "transaction" key)
    resp_headers = {"Payment-Response": base64.b64encode(
        json.dumps({"success": True, "transaction": "TXABC123"}).encode()).decode()}
    assert _extract_settlement_tx_id(resp_headers) == "TXABC123"
    legacy_headers = {"X-Payment-Response": base64.b64encode(
        json.dumps({"settleTxnId": "TXL1"}).encode()).decode()}
    assert _extract_settlement_tx_id(legacy_headers) == "TXL1"
    assert _extract_settlement_tx_id({}) == ""

    # 5. Evidence ref formatting preserves fields
    fmt = _format_evidence_ref({"evidence_id": "ev1", "type": "image",
                                "finding": "found it", "facts": [{"text": "fact"}], "sources": ["src"]})
    assert fmt["evidence_id"] == "ev1"
    assert fmt["type"] == "image"
    assert fmt["text"] == "found it"
    assert fmt["facts"] == [{"text": "fact"}]

    print("evidence_client demo: all checks passed")


if __name__ == "__main__":
    _demo()
