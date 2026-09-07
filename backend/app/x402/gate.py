"""Real x402 payment gate for Algorand (AVM) using the official Python SDK.

Replaces the earlier shim. Uses x402-avm's ExactAvmServerScheme + the FastAPI
payment middleware to serve standards-conformant 402 PAYMENT-REQUIRED
challenges, verify payments through the GoPlausible facilitator, and settle
on-chain. Mirrors the Node @x402/avm resource server factory.

Enables the Bazaar discovery extension (x402-global-challenge tag) and one
shared payTo address across all atomic capabilities, exactly like the Node
orchestrator.
"""
import base64
import json

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import RouteConfig
from x402.mechanisms.avm import (
    ALGORAND_TESTNET_CAIP2,
    ALGORAND_MAINNET_CAIP2,
    USDC_TESTNET_ASA_ID,
    USDC_MAINNET_ASA_ID,
)
from x402.mechanisms.avm.exact import ExactAvmServerScheme
from x402.server import x402ResourceServer

from .. import config


def _network() -> str:
    return ALGORAND_TESTNET_CAIP2 if config.ALGORAND_NETWORK == "testnet" else ALGORAND_MAINNET_CAIP2


def _asset_id() -> int:
    return USDC_TESTNET_ASA_ID if config.ALGORAND_NETWORK == "testnet" else USDC_MAINNET_ASA_ID


def build_x402_middleware():
    """Build and return the FastAPI payment middleware for the 6 atomic
    capabilities. Shared payTo across all endpoints (Composite entry)."""
    pay_to = config.INQUVIA_PAYTO_ADDRESS.strip()
    facilitator_url = config.X402_FACILITATOR_URL or None

    facade = HTTPFacilitatorClient(FacilitatorConfig(url=facilitator_url))
    server = x402ResourceServer(facade)
    server.register(_network(), ExactAvmServerScheme())
    try:
        server.initialize()
    except Exception as e:
        import warnings
        warnings.warn(
            f"[x402] Facilitator initialization failed (offline?): {e}. "
            "Payment gating will be skipped until the server is reachable.",
            RuntimeWarning,
            stacklevel=2,
        )

    def price_str(price_usdc: float) -> str:
        return f"${price_usdc:.6f}".rstrip("0").rstrip(".")

    routes: dict[str, RouteConfig] = {}
    for cap in config.PAID_CAPABILITIES:
        amount_micro = round(cap["priceUsdc"] * 1_000_000)
        routes[f"POST {cap['endpoint']}"] = RouteConfig(
            accepts=PaymentOption(
                scheme="exact",
                pay_to=pay_to,
                price={"asset": str(_asset_id()), "amount": str(amount_micro)},
                network=_network(),
                extra={"tag": config.X402_CHALLENGE_TAG},
            ),
            description=f"Inquvia: {cap['title']} - {cap['description']}",
            mime_type="application/json",
        )

    return payment_middleware(routes, server)


def extract_settlement_tx_id_from_response_headers(headers: dict) -> str:
    """Parse the PAYMENT-RESPONSE / X-PAYMENT-RESPONSE header for the settle
    tx id, mirroring atomicRoute.extractSettlementTxId."""
    lower_headers = {str(k).lower(): v for k, v in headers.items()}
    for name in ("payment-response", "x-payment-response", "x-x402-payment", "payment-signature"):
        header = lower_headers.get(name)
        if not header:
            continue
        try:
            decoded = base64.b64decode(header).decode("utf-8")
            parsed = json.loads(decoded)
            tx = parsed.get("settleTxnId") or parsed.get("txId") or parsed.get("transactionId") or parsed.get("transaction")
            if isinstance(tx, dict):
                tx = tx.get("txId") or tx.get("signature") or tx.get("hash")
            if tx:
                return tx
        except Exception:
            try:
                parsed = json.loads(header)
                tx = parsed.get("settleTxnId") or parsed.get("txId") or parsed.get("transactionId")
                if tx:
                    return tx
            except Exception:
                continue
    return ""


async def _record_paid_request(request, response) -> None:
    """Record a settled x402 payment from the middleware's verified request
    state, attributed to the investigation + capability returned in the
    response body. Runs only after a successful (<400) capability response,
    because the middleware settles on success."""
    from fastapi import Request  # noqa
    from .. import db, config

    requirements = getattr(request.state, "payment_requirements", None)
    if not requirements:
        return
    scheme = getattr(requirements, "scheme", None)
    if scheme != "exact":
        return

    amount_micro = int((getattr(requirements, "amount", None) or 0) or 0)
    amount_usdc = amount_micro / 1_000_000 if amount_micro else 0.0

    user = None
    headers = getattr(request, "headers", {}) or {}
    auth_header = headers.get("Authorization") if hasattr(headers, "get") else None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            from ..auth import verify_jwt
            user_id = verify_jwt(token)
            if user_id:
                user = db.get_user_by_id(user_id)
        except Exception:
            user = None
    if not user:
        cookies = getattr(request, "cookies", {}) or {}
        session_id = cookies.get(config.SESSION_COOKIE) if hasattr(cookies, "get") else None
        if session_id:
            try:
                from ..auth import get_current_user_from_cookie
                user = get_current_user_from_cookie(session_id)
            except Exception:
                user = None
    if not user:
        return

    tx_id = extract_settlement_tx_id_from_response_headers(dict(response.headers)) or ""

    # Attribute the capability payment to the investigation returned by the
    # atomic endpoint (the middlewares settles after the route produced it).
    investigation_id = None
    capability = None
    try:
        raw_body = getattr(response, "body", b"")
        if callable(raw_body):
            import inspect
            raw_body = await raw_body() if inspect.iscoroutinefunction(raw_body) else raw_body()
        import json as _json
        data = _json.loads(raw_body)
        investigation_id = data.get("id")
        capability = data.get("capability")
    except Exception:
        pass

    db.save_payment({
        "userId": user["id"],
        "investigationId": investigation_id,
        "capability": capability,
        "amount": amount_usdc,
        "currency": "USDC",
        "network": getattr(requirements, "network", None) or config.ALGORAND_NETWORK_CAIP2,
        "protocol": "x402",
        "status": "settled",
        "settlementRef": tx_id,
        "timestamp": None,
    })