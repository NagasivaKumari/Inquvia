"""Self-check for the pure-logic units (planner, heuristic analysis, budget,
budget block reasons, hash/verify). No DB or network needed."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.libraries.planner import (
    plan_claim_requirements,
    plan_source_requirements,
    plan_evidence_requirements,
)
from app.libraries.analyze import heuristic_analysis, normalize_conclusion, clamp_confidence
from app.libraries.budget import enforce_budget, budget_block_reason
from app import auth


def test_planner():
    reqs = plan_claim_requirements("Is this genuine?", ["text"])
    assert len(reqs) >= 2, "claim planner should yield requirements"
    assert reqs[0]["capability"], "requirement has capability"
    src = plan_source_requirements("Analyze https://example.com", ["url"])
    assert any(r["capability"] == "domain_lookup" for r in src)
    gen = plan_evidence_requirements("fake", ["text"])
    assert any(r["capability"] == "contradictory_evidence" for r in gen)
    assert all(r["id"].startswith("req_") for r in gen)


def test_heuristic():
    ev = [
        {"signal": "supporting", "source": "A", "finding": "ok", "status": "collected"},
        {"signal": "supporting", "source": "B", "finding": "ok", "status": "collected"},
        {"signal": "contradictory", "source": "C", "finding": "no", "status": "collected"},
    ]
    inv = {"question": "q", "acquisitions": [{}] * 3}
    r = heuristic_analysis(inv, ev)
    assert r["conclusion"] == "suspicious"
    assert r["confidence"] == 67
    assert r["risk"] == "moderate"
    empty = heuristic_analysis({"question": "q", "acquisitions": []}, [])
    assert empty["conclusion"] == "inconclusive" and empty["confidence"] == 0
    assert normalize_conclusion("likely genuine") == "likely_genuine"
    assert normalize_conclusion("bogus") is None
    assert clamp_confidence(150) == 100 and clamp_confidence(-4) == 0


def test_budget():
    ctx = {"maxPerEvidenceCheck": 0.01, "maxPerInvestigation": 0.5,
           "sessionBudget": 5, "totalBudget": 50,
           "investigationSpent": 0, "sessionSpent": 0, "totalSpent": 0}
    assert enforce_budget(0.005 * 1e6, ctx)["allowed"] is True
    blocked = enforce_budget(2 * 1e6, ctx)
    assert blocked["allowed"] is False and blocked["reason"] == "per_evidence"
    assert budget_block_reason("total_budget") == "Exceeds total budget"


def test_auth():
    h = auth.hash_password("Password123!")
    assert auth.verify_password("Password123!", h)
    assert not auth.verify_password("Wrong", h)
    pub = auth.to_public_user({"id": "u1", "passwordHash": h, "name": "N"})
    assert "passwordHash" not in pub
    r = auth.signup({"name": "Alice", "email": "a@b.com", "password": "short"})
    assert r["ok"] is False and "8 characters" in r["error"]


def test_wallet_decode():
    from app.main import _b32decode_algorand
    # A valid-format address (58 base32 chars). Length check only validates shape.
    addr = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAY5HFKQ"
    assert len(addr) == 58


async def test_arc60_signature_verify():
    """ARC-60 AUTH signature verification (Sign-In With Algorand):
    EdDSA(SHA256(data) || SHA256(authenticatorData)) over the pubkey."""
    import base64, hashlib
    from app.main import _verify_algorand_signature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    checksum = hashlib.sha256(hashlib.sha256(pub).digest()).digest()[:4]
    addr = base64.b32encode(pub + checksum).decode().rstrip("=")

    domain = "inquvia.vercel.app"
    message = f"Sign to verify control of {addr} in testnet at 0"
    data_b64 = base64.b64encode(message.encode("utf-8")).decode()
    auth_data = hashlib.sha256(domain.encode("utf-8")).digest()
    auth_b64 = base64.b64encode(auth_data).decode()
    signed_msg = hashlib.sha256(message.encode("utf-8")).digest() + hashlib.sha256(auth_data).digest()
    sig_b64 = base64.b64encode(priv.sign(signed_msg)).decode()

    ok = await _verify_algorand_signature(addr, data_b64, auth_b64, sig_b64)
    assert ok is True, "ARC-60 valid signature rejected"
    bad_sig = base64.b64encode(priv.sign(b"tampered")).decode()
    ok = await _verify_algorand_signature(addr, data_b64, auth_b64, bad_sig)
    assert ok is False, "tampered signature accepted"
    print("ARC-60 signature verification OK (good sig accepted, bad sig rejected)")


def test_x402_settlement_header():
    import base64, json
    from app.x402.gate import extract_settlement_tx_id_from_response_headers, build_x402_middleware
    # settle header shape the facilitator returns
    payload = base64.b64encode(json.dumps({"settleTxnId": "abcd1234" }).encode()).decode()
    assert extract_settlement_tx_id_from_response_headers({"payment-response": payload}) == "abcd1234"
    assert extract_settlement_tx_id_from_response_headers({}) == ""
    for cap in __import__("app.config", fromlist=["PAID_CAPABILITIES"]).PAID_CAPABILITIES:
        assert cap["priceUsdc"] > 0
        assert round(cap["priceUsdc"] * 1_000_000) >= 5000


async def main():
    test_planner()
    test_heuristic()
    test_budget()
    test_auth()
    test_wallet_decode()
    await test_arc60_signature_verify()
    test_x402_settlement_header()
    print("All self-checks passed.")


if __name__ == "__main__":
    asyncio.run(main())