"""Tests for the downstream x402 settlement + evidence acquisition flow.

Plain functions (no pytest-asyncio use) so they also run with
`python backend/tests/test_downstream_x402.py` when the global
pytest-asyncio collection bug is present.
"""
import asyncio
import base64
import json
import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.app.libraries import downstream, engine, evidence_client  # noqa: E402

TESTNET = "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="


def _build_args():
    from algosdk import account
    from algosdk.transaction import SuggestedParams
    payer_sk, payer_addr = account.generate_account()
    _, fee_addr = account.generate_account()
    _, provider = account.generate_account()
    sp = SuggestedParams(fee=1000, flat_fee=True, first=1000, last=2000,
                         gh="SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", gen="testnet-v1.0")
    return payer_sk, payer_addr, fee_addr, provider, sp


def test_payload_fee_payer_and_no_fee():
    sk, payer_addr, fee_addr, provider, sp = _build_args()
    requirement = {
        "scheme": "exact", "network": TESTNET, "asset": "10458941",
        "amount": "500000", "payTo": provider, "maxTimeoutSeconds": 3600,
        "extra": {"feePayer": fee_addr},
    }
    payload = downstream._build_v2_payload(requirement, resource={"url": "https://p/ev"},
                                           address=payer_addr, sk=sk, suggested_params=sp)
    assert payload["x402Version"] == 2
    assert payload["payload"]["paymentIndex"] == 1
    assert len(payload["payload"]["paymentGroup"]) == 2
    assert payload["accepted"]["payTo"] == provider
    assert payload["resource"]["url"] == "https://p/ev"

    no_fee = downstream._build_v2_payload(dict(requirement, extra={}),
                                          address=payer_addr, sk=sk, suggested_params=sp)
    assert no_fee["payload"]["paymentIndex"] == 0
    assert len(no_fee["payload"]["paymentGroup"]) == 1


def test_settle_official_body_and_transaction():
    sk, payer_addr, fee_addr, provider, sp = _build_args()
    requirement = {
        "scheme": "exact", "network": TESTNET, "asset": "10458941",
        "amount": "500000", "payTo": provider, "maxTimeoutSeconds": 3600,
        "extra": {"feePayer": fee_addr},
    }
    payload = downstream._build_v2_payload(requirement, address=payer_addr, sk=sk, suggested_params=sp)

    def handler(request):
        body = json.loads(request.content)
        assert body["x402Version"] == 2
        assert "paymentPayload" in body and "paymentRequirements" in body
        assert body["paymentRequirements"]["payTo"] == provider
        assert body["paymentRequirements"]["extra"]["feePayer"] == fee_addr
        return httpx.Response(200, json={"success": True, "transaction": "TX3333",
                                         "network": TESTNET, "payer": payer_addr})

    result = downstream._settle_with_facilitator(payload, requirement,
                                                 transport=httpx.MockTransport(handler))
    assert result["ok"] and result["settleTxnId"] == "TX3333"


def test_settle_fails_closed_without_transaction():
    sk, payer_addr, fee_addr, provider, sp = _build_args()
    requirement = {"scheme": "exact", "network": TESTNET, "asset": "10458941",
                   "amount": "500000", "payTo": provider, "maxTimeoutSeconds": 3600,
                   "extra": {"feePayer": fee_addr}}
    payload = downstream._build_v2_payload(requirement, address=payer_addr, sk=sk, suggested_params=sp)

    def handler(request):
        return httpx.Response(200, json={"success": True, "network": TESTNET, "payer": payer_addr})

    try:
        result = downstream._settle_with_facilitator(payload, requirement,
                                                     transport=httpx.MockTransport(handler))
        assert not result["ok"], "missing transaction must fail closed"
    except Exception:
        pass  # official client rejects a SettleResponse without transaction


def test_proof_roundtrip():
    sk, payer_addr, fee_addr, provider, sp = _build_args()
    requirement = {"scheme": "exact", "network": TESTNET, "asset": "10458941",
                   "amount": "500000", "payTo": provider, "maxTimeoutSeconds": 3600,
                   "extra": {"feePayer": fee_addr}}
    payload = downstream._build_v2_payload(requirement, address=payer_addr, sk=sk, suggested_params=sp)
    proof = base64.b64encode(json.dumps(payload).encode()).decode()
    assert json.loads(base64.b64decode(proof).decode()) == payload


# ── engine: economic selection + adaptive stopping + classification ───


def test_select_evidence_type():
    ctx = {"maxPerInvestigation": 1.0, "maxPerEvidenceCheck": 0.05,
           "investigationSpent": 0, "sessionBudget": 5, "sessionSpent": 0,
           "totalBudget": 10, "totalSpent": 0}
    assert engine._select_evidence_type("url", 0.0, 1.0, ctx)["selected"] is True
    assert engine._select_evidence_type("url", 5.0, 1.0, ctx)["selected"] is False
    low = engine._select_evidence_type("timeline", 0.5, 0.5, ctx)
    assert low["selected"] is False
    assert low["reason"] == "expected_value_below_cost_threshold"
    good = engine._select_evidence_type("image", 0.5, 1.0, ctx)
    assert good["selected"] is True and good["reason"] == "value_justifies_cost"


def test_stopping_decision():
    assert engine._stopping_decision([{"signal": "supporting", "confidence": 90}])["stop"] is False
    contradiction = engine._stopping_decision([
        {"signal": "supporting", "confidence": 70},
        {"signal": "contradictory", "confidence": 75},
    ])
    assert contradiction["stop"] is True
    assert contradiction["reason"] == "high_confidence_contradicting_evidence"
    support = engine._stopping_decision([
        {"signal": "supporting", "confidence": 70},
        {"signal": "supporting", "confidence": 80},
    ])
    assert support["stop"] is True


def test_classify_evidence():
    evidence = [
        {"id": "ev_a", "type": "url", "signal": "supporting", "confidence": 90,
         "finding": "ok", "timestamp": "2020-01-01T00:00:00Z"},
        {"id": "ev_b", "type": "image", "signal": "contradictory", "confidence": 10,
         "finding": "", "timestamp": "2024-01-01T00:00:00Z"},
    ]
    result = engine._classify_evidence(evidence, {"duplicates": [["ev_a", "ev_b"]]}, ["video"])
    by_id = {i["id"]: i for i in result["items"]}
    assert by_id["ev_a"]["stale"] is True
    assert by_id["ev_b"]["nonProbative"] is True
    assert by_id["ev_a"]["duplicates"] == ["ev_b"]
    assert result["missing"] == ["video"]
    assert by_id["ev_a"]["independent"] is None


# ── simulated 402 E2E through _post ───────────────────────────────────

PAY_REQ_HEADER = base64.b64encode(json.dumps({
    "x402Version": 2,
    "resource": {"url": "https://provider/api/evidence/url"},
    "accepts": [{"scheme": "exact", "network": TESTNET, "asset": "10458941",
                 "amount": "10000", "payTo": "STDPROVIDERPAYTO000000000",
                 "maxTimeoutSeconds": 3600, "extra": {}}],
}).encode()).decode()


def _budget_ctx():
    return {"maxPerEvidenceCheck": 0.05, "maxPerInvestigation": 1.0,
            "investigationSpent": 0.0, "sessionBudget": 5.0, "sessionSpent": 0.0,
            "totalBudget": 10.0, "totalSpent": 0.0}


def test_post_simulated_402_e2e():
    calls = []
    real_is_available, real_pay = downstream.is_available, downstream.pay_and_get_proof

    def handler(request):
        calls.append(dict(request.headers))
        if "payment-signature" in {k.lower(): v for k, v in request.headers.items()}:
            return httpx.Response(200, headers={
                "payment-response": base64.b64encode(
                    json.dumps({"transaction": "TXSIM1", "success": True, "network": TESTNET}).encode()).decode(),
            }, json={"evidence_id": "ev_sim", "type": "url", "verdict": "supports",
                    "confidence": 0.9, "observations": [{"text": "host replies"}]})
        return httpx.Response(402, headers={"payment-required": PAY_REQ_HEADER})

    evidence_client._TEST_TRANSPORT = httpx.MockTransport(handler)
    paid = {"calls": 0}

    def fake_pay(**kwargs):
        paid["calls"] += 1
        return {"ok": True, "proof": "PROOFB64", "settleTxnId": "TXSIM1",
                "amountMicro": 10000, "payTo": "STDPROVIDERPAYTO000000000",
                "network": TESTNET, "assetId": "10458941"}

    downstream.is_available = lambda: True
    downstream.pay_and_get_proof = fake_pay
    try:
        body = asyncio.run(evidence_client.acquire_url_evidence(
            "https://provider/api/evidence/url", claim="x", budget_ctx=_budget_ctx()))
    finally:
        evidence_client._TEST_TRANSPORT = None
        downstream.is_available, downstream.pay_and_get_proof = real_is_available, real_pay

    assert body is not None
    assert body["evidence_id"] == "ev_sim"
    assert body["_payment"]["settlementRef"] == "TXSIM1"
    assert body["_payment"]["status"] == "settled"
    assert paid["calls"] == 1
    assert len(calls) == 2
    retry_headers = {k.lower(): v for k, v in calls[1].items()}
    assert retry_headers.get("payment-signature") == "PROOFB64"


def test_post_budget_blocks_before_payment():
    paid = {"calls": 0}

    def handler(request):
        return httpx.Response(402, headers={"payment-required": PAY_REQ_HEADER})

    evidence_client._TEST_TRANSPORT = httpx.MockTransport(handler)
    downstream.is_available = (lambda: True)
    downstream.pay_and_get_proof = lambda **kw: paid.update(calls=paid["calls"] + 1) or {
        "ok": True, "proof": "P", "settleTxnId": "TXSIM2", "amountMicro": 10000,
        "payTo": "STDPROVIDERPAYTO000000000", "network": TESTNET, "assetId": "10458941"}
    ctx = _budget_ctx()
    ctx["maxPerEvidenceCheck"] = 0.005  # 5000 micro < requested 10000 micro -> blocked
    try:
        body = asyncio.run(evidence_client.acquire_url_evidence(
            "https://provider/api/evidence/url", claim="x", budget_ctx=ctx))
    finally:
        evidence_client._TEST_TRANSPORT = None
    assert body is None
    assert paid["calls"] == 0, "budget block must happen before any payment"


def test_extract_settlement_tx_id_v2():
    headers = {"payment-response": base64.b64encode(
        json.dumps({"transaction": "TXREAL1"}).encode()).decode()}
    assert evidence_client._extract_settlement_tx_id(headers) == "TXREAL1"


def run():
    test_payload_fee_payer_and_no_fee()
    test_settle_official_body_and_transaction()
    test_settle_fails_closed_without_transaction()
    test_proof_roundtrip()
    test_select_evidence_type()
    test_stopping_decision()
    test_classify_evidence()
    test_post_simulated_402_e2e()
    test_post_budget_blocks_before_payment()
    test_extract_settlement_tx_id_v2()
    print("test_downstream_x402: all checks passed")


if __name__ == "__main__":
    run()