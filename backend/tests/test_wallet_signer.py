"""Wallet/signer abstraction tests for downstream Tx #2 (x402, M2M).

The payer key lives in an out-of-process signer service (backend/tools/...)
started as a real uvicorn server on 127.0.0.1; Core only ever talks to it over
HTTP and never holds a private key. Exercises:
  - HttpKeyOwner + RemoteAvmSigner (x402 ClientAvmSigner adapter)
  - full testnet-parameter sign + settle flow (facilitator mocked, no funds)
  - KMS-style bare-signature wrapping
  - fail-closed when no signer is configured

Plain functions (no pytest-asyncio use) so they also run with
`python backend/tests/test_wallet_signer.py` when the global pytest-asyncio
collection bug is present.
"""
import base64
import json
import os
import pathlib
import socket
import sys
import threading
import time

os.environ.setdefault("JWT_SECRET", "wallet-signer-test-secret")
os.environ.setdefault("ALGORAND_NETWORK", "testnet")
os.environ.setdefault("ALGORAND_USDC_ASA", "10458941")
os.environ.pop("EVIDENCE_SERVICE_URL", None)
os.environ.pop("SIGNER_URL", None)

TESTNET = "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from algosdk import account, constants, encoding as _enc  # noqa: E402
from algosdk import mnemonic as _algo_mnemonic  # noqa: E402
from algosdk.transaction import AssetTransferTxn  # noqa: E402
from nacl.signing import VerifyKey  # noqa: E402
import httpx  # noqa: E402

from backend.app import config  # noqa: E402
from backend.app.libraries import downstream, wallet_signer  # noqa: E402
from backend.tools import signer_service  # noqa: E402

SIGNER_TOKEN = "test-token-abc"
PAYER_SK, PAYER_ADDR = account.generate_account()
os.environ["SIGNER_ACCOUNT_MNEMONIC"] = _algo_mnemonic.from_private_key(PAYER_SK)
os.environ["SIGNER_BEARER_TOKEN"] = SIGNER_TOKEN


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _SignerServer:
    def __init__(self):
        import uvicorn

        self._port = _free_port()
        self._app = signer_service.app_factory()
        cfg = uvicorn.Config(self._app, host="127.0.0.1", port=self._port,
                             log_level="error", access_log=False, lifespan="off")
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self):
        self._thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", self._port), timeout=0.5)
                s.close()
                return f"http://127.0.0.1:{self._port}"
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("signer service did not start")

    def __exit__(self, *exc):
        self._server.should_exit = True
        self._thread.join(timeout=10)


def _sp():
    return downstream._get_suggested_params()


def _prov_requirement(provider_addr: str, amount_micro: int = 10_000,
                      fee_payer: bool = True) -> dict:
    req = {
        "scheme": "exact",
        "network": TESTNET,
        "asset": "10458941",
        "amount": str(amount_micro),
        "payTo": provider_addr,
        "maxTimeoutSeconds": 3600,
    }
    if fee_payer:
        _sk, fee_addr = account.generate_account()
        req["extra"] = {"feePayer": fee_addr}
    else:
        req["extra"] = {}
    return req


def _verify_signed_under_key(blob_b64: str, sk: str, expect_sender: str) -> dict:
    stx = _enc.msgpack_decode(blob_b64)  # expects the base64 string of the signed txn
    txn = stx.transaction
    assert txn.sender == expect_sender, f"sender {txn.sender} != {expect_sender}"
    assert stx.signature, "transaction must carry a signature"
    from nacl.exceptions import BadSignatureError
    msg = constants.txid_prefix + base64.b64decode(_enc.msgpack_encode(txn))
    try:
        VerifyKey(base64.b64decode(sk)[32:]).verify(base64.b64decode(stx.signature) + msg)
    except BadSignatureError:
        raise AssertionError("signature does not verify under the payer key")
    return {"sender": txn.sender, "receiver": txn.receiver or "", "amount": txn.amount,
            "asset": getattr(txn, "index", None)}


def _require_live_testnet_params() -> dict:
    try:
        r = httpx.get(f"{config.ALGOD_SERVER}/v2/transactions/params", timeout=5.0,
                      headers={"X-Algo-API-Token": config.ALGOD_TOKEN} if config.ALGOD_TOKEN else {})
        if r.status_code == 200:
            d = r.json()
            return {"last-round": d.get("last-round"), "genesis-hash": d.get("genesis-hash"),
                    "genesis-id": d.get("genesis-id")}
    except Exception:
        pass
    return {}


# ── Core contract: NO private key in Core ──────────────────────────────


def test_core_has_no_private_key_material():
    assert not hasattr(config, "SERVER_WALLET_MNEMONIC"), "mnemonic config removed"
    assert not os.environ.get("SERVER_WALLET_MNEMONIC")
    assert not config.SIGNER_URL, "signer unset in this test env"
    assert downstream.is_available() is False
    result = downstream.pay_and_get_proof("https://p/ev", "PAYTOADDR0", 10_000)
    assert result.get("ok") is False and result.get("reason") == "no_signer", result


# ── KMS-style bare signature wrapping (AWS KMS / Vault shape) ──────────


def test_kms_style_bare_signature_wrap_matches_local_signing():
    import msgpack as _mp

    from algosdk import account as _acct, encoding as _e
    from algosdk.transaction import SuggestedParams
    from nacl.signing import SigningKey

    sk, addr = _acct.generate_account()
    _, provider = _acct.generate_account()
    sp = SuggestedParams(fee=1000, flat_fee=True, first=1000, last=2000,
                         gh="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", gen="testnet-v1.0")
    txn = AssetTransferTxn(sender=addr, sp=sp, receiver=provider, amt=10_000,
                           index=10458941, note=b"kms-style")
    raw = base64.b64decode(_e.msgpack_encode(txn))

    sig = SigningKey(base64.b64decode(sk)[:32]).sign(b"TX" + raw).signature
    wrapped = wallet_signer.wrap_bare_signatures([raw], [0], {0: sig})[0]
    local = base64.b64decode(_e.msgpack_encode(txn.sign(sk)))
    assert wrapped == local
    stx = _e.msgpack_decode(base64.b64encode(wrapped).decode())
    assert stx.transaction.sender == addr and stx.transaction.receiver == provider
    assert _mp.unpackb(raw, raw=False)  # sanity: unsigned blob parses


# ── Remote Avm Signer: x402 group over the HTTP signer service ──────────


def test_remote_avm_signer_x402_payload_testnet():
    with _SignerServer() as url:
        owner = wallet_signer.HttpKeyOwner(url, api_key=SIGNER_TOKEN)
        assert owner.address == PAYER_ADDR, "signer service must report the payer it owns"
        signer = wallet_signer.RemoteAvmSigner(owner)

        _, provider = account.generate_account()
        req = _prov_requirement(provider, fee_payer=True)
        resource = {"url": "https://provider/api/evidence/url", "description": "testnet"}

        real_get = wallet_signer.get_default_signer
        wallet_signer.get_default_signer = lambda: signer
        try:
            payload = downstream._build_v2_payload(req, resource=resource, suggested_params=_sp())
        finally:
            wallet_signer.get_default_signer = real_get

        assert payload["x402Version"] == 2
        assert payload["accepted"]["payTo"] == provider
        assert payload["accepted"]["asset"] == "10458941"
        assert payload["accepted"]["amount"] == "10000"
        assert payload["payload"]["paymentIndex"] == 1

        group = payload["payload"]["paymentGroup"]
        assert len(group) == 2
        asa = _verify_signed_under_key(group[1], PAYER_SK, PAYER_ADDR)
        assert asa["receiver"] == provider and asa["amount"] == 10_000 and asa["asset"] == 10458941
        # fee-payer txn (index 0) stays unsigned for the facilitator
        import msgpack as _mp
        from algosdk.transaction import Transaction
        fee_txn = Transaction.undictify(_mp.unpackb(base64.b64decode(group[0]), raw=False))
        assert fee_txn.sender == req["extra"]["feePayer"]


# ── Fail closed when the signer rejects ────────────────────────────────


def test_http_signer_auth_rejected_fails_closed():
    with _SignerServer() as url:
        owner = wallet_signer.HttpKeyOwner(url, api_key="wrong-token")
        _, provider = account.generate_account()
        try:
            owner.sign_transactions(
                [base64.b64decode(_enc.msgpack_encode(AssetTransferTxn(
                    sender=owner.address, sp=_sp(), receiver=provider,
                    amt=1, index=10458941)))], [0])
            raise AssertionError("bad token must fail closed")
        except wallet_signer.SignerUnavailable:
            pass


# ── Full M2M flow: 402 -> sign via signer -> facilitator -> proof ──────


def test_sign_and_settle_flow_testnet():
    live = _require_live_testnet_params()
    with _SignerServer() as url:
        owner = wallet_signer.HttpKeyOwner(url, api_key=SIGNER_TOKEN)
        signer = wallet_signer.RemoteAvmSigner(owner)
        _, provider = account.generate_account()
        requirement = _prov_requirement(provider, amount_micro=10_000, fee_payer=True)
        resource = {"url": "https://provider/api/evidence/url", "description": "testnet"}

        real_get = wallet_signer.get_default_signer
        wallet_signer.get_default_signer = lambda: signer
        try:
            payload = downstream._build_v2_payload(requirement, resource=resource,
                                                   suggested_params=_sp())
        finally:
            wallet_signer.get_default_signer = real_get

        captured = {}

        def settle_handler(request):
            body = json.loads(request.content)
            captured["version"] = body["x402Version"]
            captured["payTo"] = body["paymentRequirements"]["payTo"]
            captured["feePayer"] = body["paymentRequirements"].get("extra", {}).get("feePayer")
            return httpx.Response(200, json={
                "success": True, "transaction": "TX-TEST-SETTLE-1",
                "network": requirement["network"], "payer": PAYER_ADDR})

        settle = downstream._settle_with_facilitator(
            payload, requirement, transport=httpx.MockTransport(settle_handler))
        assert settle["ok"], settle
        assert settle["settleTxnId"] == "TX-TEST-SETTLE-1"
        assert captured["version"] == 2
        assert captured["payTo"] == provider
        assert captured["feePayer"] == requirement["extra"]["feePayer"]

        proof = base64.b64encode(json.dumps(payload).encode()).decode()
        assert json.loads(base64.b64decode(proof).decode()) == payload

        asa = _verify_signed_under_key(payload["payload"]["paymentGroup"][1], PAYER_SK, PAYER_ADDR)
        assert asa["receiver"] == provider and asa["amount"] == 10_000
        assert asa["asset"] == 10458941
        assert live.get("genesis-hash") or not live, "live testnet params when reachable"


def run():
    test_core_has_no_private_key_material()
    test_kms_style_bare_signature_wrap_matches_local_signing()
    test_remote_avm_signer_x402_payload_testnet()
    test_http_signer_auth_rejected_fails_closed()
    test_sign_and_settle_flow_testnet()
    print("test_wallet_signer: all checks passed")


if __name__ == "__main__":
    run()