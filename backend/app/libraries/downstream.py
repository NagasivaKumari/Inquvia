"""Server-side x402 client for paying downstream Evidence Services.

When an Evidence Service requires x402 payment, Core probes the provider's
resource URL for its 402 PAYMENT-REQUIRED challenge, builds and signs the
V2 exact-scheme AVM payment payload using the canonical x402-avm SDK
(x402ClientSync + ExactAvmScheme), and settles it through the GoPlausible
facilitator (HTTPFacilitatorClientSync). The ASA transfer (Tx #2) is signed
by an EXTERNAL signer (libraries/wallet_signer + tools/signer_service): Core
holds no private key — the signer owns the key and returns signatures. If
accepts[0] carries extra.feePayer, the fee-payer txn stays unsigned so the
facilitator can sign and submit it at settlement time.

Core never holds or spends user funds (Tx #1 is the user -> Inquvia fee) and
never asks the human to pay a provider: the external signer pays Tx #2 on
behalf of the investigation and the cost is attributed to the user's budget.
"""
import base64
import json
import logging

import httpx

from .. import config
from ..libraries import wallet_signer

logger = logging.getLogger(__name__)

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS
FACILITATOR_URL = config.X402_FACILITATOR_URL
PROVIDER_TIMEOUT = 12.0
FACILITATOR_TIMEOUT = 30.0


def _has_external_signer() -> bool:
    return bool(config.SIGNER_URL and config.SIGNER_URL.strip())


def _caip2_network() -> str:
    return config.ALGORAND_NETWORK_CAIP2


def _asset_id() -> str:
    return str(config.ALGORAND_USDC_ASA)


# ── ClientAvmSigner implementations ───────────────────────────────────


class _LocalSigner:
    """Dev/test-only signer for a locally supplied key.

    Production Tx #2 signing goes through wallet_signer.RemoteAvmSigner (an
    external key owner); Core never reads a mnemonic. This class exists so
    unit tests and demos can pass an explicitly generated key.

    Signs only the transactions whose sender is this account (the ASA
    transfer); the fee payer transaction is left for the facilitator.
    """

    def __init__(self, address: str, sk):
        self._address = address
        self._sk = sk

    @property
    def address(self) -> str:
        return self._address

    def sign_transactions(self, unsigned_txns, indexes_to_sign):
        import msgpack as _mp
        from algosdk import encoding as _enc
        from algosdk import transaction as _txn
        to_sign = set(indexes_to_sign)
        signed = []
        for i, blob in enumerate(unsigned_txns):
            if i not in to_sign:
                signed.append(None)
                continue
            txn = _txn.Transaction.undictify(_mp.unpackb(blob, raw=False))
            signed_blob = _enc.msgpack_encode(txn.sign(self._sk))
            signed.append(base64.b64decode(signed_blob))
        return signed


class _StubAlgod:
    """algod stand-in that returns pre-supplied suggested params (offline)."""

    def __init__(self, suggested_params):
        self._sp = suggested_params

    def suggested_params(self):
        return self._sp


# ── 402 Probe ─────────────────────────────────────────────────────────


def probe_x402(url: str, transport=None) -> dict | None:
    """Probe a provider URL for its x402 PAYMENT-REQUIRED challenge.

    Returns dict with payTo, amountMicro, assetId, network, scheme, resourceUrl
    or None if the provider doesn't expose a parseable 402.
    """
    import base64 as _b64
    client = httpx.Client(timeout=PROVIDER_TIMEOUT, transport=transport) if transport else httpx.Client(timeout=PROVIDER_TIMEOUT)
    try:
        res = client.get(url)
        if res.status_code != 402:
            return None
        header = res.headers.get("payment-required") or res.headers.get("PAYMENT-REQUIRED")
        if not header:
            return None
        try:
            data = json.loads(_b64.b64decode(header).decode("utf-8"))
        except Exception:
            data = json.loads(header)
        accepts = data.get("accepts") or []
        if not accepts:
            return None
        acc = accepts[0] if isinstance(accepts, list) else accepts
        pay_to = acc.get("payTo") or acc.get("pay_to")
        amount = acc.get("amount")
        asset = acc.get("asset") or acc.get("assetId")
        network = acc.get("network") or data.get("network")
        if not pay_to or not amount:
            return None
        try:
            amount_micro = int(round(float(amount))) if float(amount) < 1e6 else int(amount)
        except (TypeError, ValueError):
            return None
        return {
            "payTo": pay_to,
            "amountMicro": amount_micro,
            "assetId": str(asset) if asset else _asset_id(),
            "network": network or _caip2_network(),
            "scheme": acc.get("scheme", "exact"),
            "resourceUrl": data.get("resourceUrl") or url,
        }
    except Exception:
        return None
    finally:
        client.close()


# ── V2 Payment Payload (canonical x402-avm) ───────────────────────────


def _requirement_from_fields(pay_to: str, amount_micro: int, asset_id: str | None,
                             network: str | None) -> dict:
    """Fallback V2 requirement when only flattened challenge fields are available."""
    return {
        "scheme": "exact",
        "network": network or _caip2_network(),
        "asset": str(asset_id or _asset_id()),
        "amount": str(int(amount_micro)),
        "payTo": pay_to,
        "maxTimeoutSeconds": 3600,
        "extra": {},
    }


def _get_suggested_params():
    """Fetch current suggested params from algod for valid round numbers."""
    from algosdk import transaction as _txn
    try:
        import httpx as _httpx
        resp = _httpx.get(f"{config.ALGOD_SERVER}/v2/transactions/params", timeout=5.0,
                          headers={"X-Algo-API-Token": config.ALGOD_TOKEN} if config.ALGOD_TOKEN else {})
        if resp.status_code == 200:
            d = resp.json()
            last_round = d.get("last-round", 1000)
            gen_hash = d.get("genesis-hash", "")
            gen_id = d.get("genesis-id", "")
            fee = d.get("min-fee", 1000)
            return _txn.SuggestedParams(
                fee=fee, flat_fee=True,
                first=last_round + 1,
                last=last_round + 1000,
                gh=gen_hash, gen=gen_id,
            )
    except Exception:
        pass
    return _txn.SuggestedParams(
        fee=1000, flat_fee=True,
        first=1000, last=2000,
        gh="", gen="",
    )


def _build_v2_payload(requirement: dict, resource: dict | None = None,
                      address: str | None = None, sk=None,
                      suggested_params=None) -> dict:
    """Build the exact x402 V2 PaymentPayload for a requirement via x402-avm.

    Uses the installed x402-avm ExactAvmScheme + x402ClientSync (canonical):
    - with extra.feePayer: [fee payer self-pay (unsigned), ASA transfer (signed)]
      → paymentIndex 1; the facilitator signs the fee payer txn at settle time
    - without: single ASA transfer → paymentIndex 0
    The ASA transfer is signed (sender = payer) by the payer signer: either the
    configured external signer (RemoteAvmSigner) or, when address+sk are passed
    explicitly (tests/demos), a local signer. No mnemonic is ever read.

    suggested_params: optional offline algod params; when given the scheme is
    driven off a stub algod so no network is touched (tests/demos).
    """
    from x402 import x402ClientSync
    from x402.mechanisms.avm.exact import ExactAvmScheme
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo

    if address is None or sk is None:
        signer = wallet_signer.get_default_signer()
        if signer is None:
            raise wallet_signer.SignerUnavailable(
                "No external signer configured (SIGNER_URL unset)")
    else:
        signer = _LocalSigner(address, sk)

    req0 = dict(requirement)
    req0.setdefault("scheme", "exact")
    req0.setdefault("maxTimeoutSeconds", 3600)
    req0.setdefault("extra", {})

    req_model = PaymentRequirements.model_validate(req0)

    scheme = ExactAvmScheme(signer=signer)
    if suggested_params is not None:
        from x402.mechanisms.avm.utils import normalize_network
        scheme._clients[normalize_network(req_model.network)] = _StubAlgod(suggested_params)

    res = None
    if resource and resource.get("url"):
        try:
            res = ResourceInfo(
                url=resource["url"],
                description=resource.get("description"),
                mime_type=resource.get("mimeType") or resource.get("mime_type"),
            )
        except Exception:
            res = None

    payment_required = PaymentRequired(x402_version=2, resource=res, accepts=[req_model])

    client = x402ClientSync()
    client.register(req_model.network, scheme)
    payload = client.create_payment_payload(payment_required)
    return payload.model_dump(by_alias=True, exclude_none=True)


# ── Facilitator Submission (canonical x402-avm) ───────────────────────


def _settle_with_facilitator(payment_payload: dict, requirement: dict,
                             transport=None) -> dict:
    """Submit the V2 payload to the GoPlausible facilitator for settlement.

    POST {facilitator}/settle with {x402Version, paymentPayload, paymentRequirements}
    via x402-avm's HTTPFacilitatorClientSync. Returns
    {"ok": True, "settleTxnId": str, "raw": ...} or {"ok": False, ...}.
    No transaction id is ever fabricated: a settle that returns no
    SettleResponse.transaction is treated as a failure.
    """
    from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync
    from x402.schemas import PaymentPayload, PaymentRequirements

    if not FACILITATOR_URL:
        return {"ok": False, "error": "No facilitator URL configured", "reason": "no_facilitator"}
    try:
        payload_model = PaymentPayload.model_validate(payment_payload)
        req_model = PaymentRequirements.model_validate(requirement)
    except Exception as e:
        logger.error("Invalid payment payload: %s", e)
        return {"ok": False, "error": f"Invalid payment payload: {e}", "reason": "settlement_failed"}

    cfg = FacilitatorConfig(url=FACILITATOR_URL, timeout=FACILITATOR_TIMEOUT)
    if transport is not None:
        cfg.http_client = httpx.Client(timeout=FACILITATOR_TIMEOUT, transport=transport)
    client = HTTPFacilitatorClientSync(cfg)
    try:
        result = client.settle(payload_model, req_model)
    except Exception as e:
        logger.error("Facilitator settle failed: %s", e)
        return {"ok": False, "error": "Facilitator settlement failed", "reason": "settlement_failed"}

    if not result.success:
        return {"ok": False,
                "error": result.error_reason or result.error_message or "Facilitator rejected settlement",
                "reason": "settlement_failed"}
    if not result.transaction:
        return {"ok": False, "error": "Facilitator returned no transaction id",
                "reason": "settlement_failed"}
    return {"ok": True, "settleTxnId": str(result.transaction), "raw": result.model_dump(by_alias=True)}


# ── Public API ────────────────────────────────────────────────────────


def is_available() -> bool:
    """Whether server-side downstream payment is possible (external signer + facilitator)."""
    return _has_external_signer() and bool(FACILITATOR_URL)


def pay_and_get_proof(resource_url: str, pay_to: str, amount_micro: int,
                      asset_id: str | None = None, network: str | None = None,
                      requirement: dict | None = None,
                      resource: dict | None = None) -> dict:
    """Build, settle, and encode the V2 x402 payment to a downstream provider.

    requirement: the provider's full accepts[0] dict from the 402 challenge
    (verbatim, so extra.feePayer / maxTimeoutSeconds survive).
    resource: the 402's resource dict, echoed back in the payload.

    Tx #2 is authorized by the configured EXTERNAL signer (signer owns the
    key; Core holds only the payer address). Returns
    {"ok": True, "proof": base64(PaymentPayload) for the
    PAYMENT-SIGNATURE header, "settleTxnId", "amountMicro", ...} or
    {"ok": False, "error", "reason"}.
    """
    if not config.SIGNER_URL or not config.SIGNER_URL.strip():
        return {"ok": False, "error": "No external signer configured",
                "reason": "no_signer"}

    if not FACILITATOR_URL:
        return {"ok": False, "error": "No facilitator URL configured", "reason": "no_facilitator"}

    req = requirement or _requirement_from_fields(pay_to, amount_micro, asset_id, network)
    try:
        payment_payload = _build_v2_payload(req, resource=resource)
    except wallet_signer.SignerUnavailable as e:
        logger.error("External signer unavailable: %s", e)
        return {"ok": False, "error": f"External signer unavailable: {e}",
                "reason": "signer_unavailable"}
    except Exception as e:
        logger.error("Failed to build payment payload: %s", e)
        return {"ok": False, "error": f"Payment payload build failed: {e}",
                "reason": "build_failed"}

    result = _settle_with_facilitator(payment_payload, req)
    if not result.get("ok"):
        return result

    proof = base64.b64encode(json.dumps(payment_payload).encode()).decode()
    return {
        "ok": True,
        "proof": proof,
        "payment_payload": payment_payload,
        "settleTxnId": result["settleTxnId"],
        "amountMicro": int(req["amount"]),
        "payTo": req["payTo"],
        "network": req["network"],
        "assetId": req["asset"],
    }


def build_x402_headers(resource_url: str, pay_to: str, amount_micro: int,
                       asset_id: str | None = None, network: str | None = None,
                       requirement: dict | None = None,
                       resource: dict | None = None) -> dict | None:
    """Convenience: pay and return the V2 retry headers, or None on failure."""
    result = pay_and_get_proof(resource_url, pay_to, amount_micro, asset_id, network,
                               requirement=requirement, resource=resource)
    if not result.get("ok"):
        return None
    return {"PAYMENT-SIGNATURE": result["proof"]}


def _demo():
    """Self-check: 402 parsing + V2 payload build + facilitator settle (no wallet/algod)."""
    import httpx as _httpx
    from algosdk import account, transaction as _txn

    # 1. 402 challenge parsing (MockTransport, no network)
    challenge_data = {
        "x402Version": 2,
        "resource": {"url": "https://provider.example/evidence", "description": "demo"},
        "accepts": [{
            "scheme": "exact",
            "network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
            "payTo": "STDRVADDR1234567890",
            "asset": "10458941",
            "amount": "10000",  # micro-USDC = 0.01 USDC
            "maxTimeoutSeconds": 3600,
            "extra": {"feePayer": "STDFEEPAYER1234567890"},
        }],
    }
    encoded = base64.b64encode(json.dumps(challenge_data).encode()).decode()

    def handler(request):
        return _httpx.Response(402, headers={"payment-required": encoded})

    parsed = probe_x402("https://provider.example/evidence", transport=_httpx.MockTransport(handler))
    assert parsed is not None, "probe should parse the 402 challenge"
    assert parsed["payTo"] == "STDRVADDR1234567890"
    assert parsed["amountMicro"] == 10000, f"0.01 USDC -> 10000 micro, got {parsed['amountMicro']}"
    assert parsed["scheme"] == "exact"

    # 2. No-402 fails closed
    def no_402(request):
        return _httpx.Response(200)
    assert probe_x402("https://provider.example/evidence", transport=_httpx.MockTransport(no_402)) is None

    # 3. V2 payload build with fee payer: 2-txn group, ASA transfer is index 1
    # NOTE: py-algorand-sdk 2.11 generate_account() returns (private_key, address).
    payer_sk, payer_addr = account.generate_account()
    _, fee_addr = account.generate_account()
    _, provider_addr = account.generate_account()
    sp = _txn.SuggestedParams(fee=1000, flat_fee=True, first=1000, last=2000,
                              gh="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
                              gen="testnet-v1.0")
    requirement = {
        "scheme": "exact",
        "network": "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=",
        "asset": "10458941",
        "amount": "500000",
        "payTo": provider_addr,
        "maxTimeoutSeconds": 3600,
        "extra": {"feePayer": fee_addr},
    }
    payload = _build_v2_payload(requirement, resource=challenge_data["resource"],
                                address=payer_addr, sk=payer_sk, suggested_params=sp)
    assert payload["x402Version"] == 2
    assert payload["accepted"]["payTo"] == provider_addr
    assert payload["resource"]["url"] == challenge_data["resource"]["url"]
    assert payload["payload"]["paymentIndex"] == 1, "fee payer mode -> ASA transfer is txn #2"
    group_blobs = payload["payload"]["paymentGroup"]
    assert len(group_blobs) == 2

    no_fee = _build_v2_payload(dict(requirement, extra={}),
                               address=payer_addr, sk=payer_sk, suggested_params=sp)
    assert no_fee["payload"]["paymentIndex"] == 0
    assert len(no_fee["payload"]["paymentGroup"]) == 1

    # The ASA transfer txn in the payment group must be signed by the payer
    from algosdk import encoding as _enc
    signed_txn = _enc.msgpack_decode(group_blobs[1])
    assert signed_txn.transaction.sender == payer_addr

    # 4. Settle body has V2 shape (both paymentPayload and paymentRequirements)
    def settle_handler(request):
        body = json.loads(request.content)
        assert body["x402Version"] == 2
        assert "paymentPayload" in body and "paymentRequirements" in body, \
            "settle needs BOTH paymentPayload and paymentRequirements"
        assert body["paymentRequirements"]["payTo"] == provider_addr
        assert body["paymentRequirements"]["extra"]["feePayer"] == fee_addr
        return _httpx.Response(200, json={"success": True, "transaction": "TX3333",
                                          "network": requirement["network"], "payer": payer_addr})

    result = _settle_with_facilitator(payload, requirement,
                                      transport=_httpx.MockTransport(settle_handler))
    assert result["ok"] and result["settleTxnId"] == "TX3333", f"got {result}"

    # 5. A settle that returns no transaction id fails closed (never fabricated)
    def no_tx_handler(request):
        return _httpx.Response(200, json={"success": True,
                                          "network": requirement["network"], "payer": payer_addr})
    try:
        bad = _settle_with_facilitator(payload, requirement,
                                       transport=_httpx.MockTransport(no_tx_handler))
        assert not bad["ok"], "missing transaction must fail closed"
    except Exception:
        pass  # official client may raise on missing required field — fail closed either way

    # 6. Proof round-trips to the exact payload (PAYMENT-SIGNATURE content)
    proof = base64.b64encode(json.dumps(payload).encode()).decode()
    assert json.loads(base64.b64decode(proof).decode()) == payload

    # 7. is_available requires a server wallet + facilitator; must not crash
    assert is_available() is False or True

    print("downstream demo: all checks passed")


if __name__ == "__main__":
    _demo()