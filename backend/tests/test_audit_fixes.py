"""Regression tests for the three read-only-audit fixes.

Plain functions (no pytest-asyncio use) so they also run with
`python backend/tests/test_audit_fixes.py` when the global pytest-asyncio
collection bug is present. Fix 1 exercises engine/gateway against mongomock;
Fix 2 and Fix 3 are pure-function tests.
"""
import asyncio
import os
import pathlib
import sys

os.environ.setdefault("JWT_SECRET", "audit-fix-test-secret")
os.environ.setdefault("ALGORAND_NETWORK", "testnet")
os.environ.setdefault("ALGORAND_USDC_ASA", "10458941")
os.environ.setdefault("MONGODB_DB_NAME", "inquvia_test_audit_fixes")
os.environ.pop("EVIDENCE_SERVICE_URL", None)
os.environ.pop("EXTERNAL_EVIDENCE_SERVICES_URL", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from backend.app import db  # noqa: E402
from backend.app.libraries import analyze, engine, gateway  # noqa: E402


def _mongo():
    import mongomock
    db._client = mongomock.MongoClient()


def _minimal_inv(inv_id: str, question: str = "Does the user own the license?") -> dict:
    return {
        "id": inv_id,
        "question": question,
        "capability": "license_verification",
        "userId": "user_audit",
        "inputs": [],
        "evidenceRequirements": [],
        "timestamp": "2026-01-01T00:00:00Z",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "acquisitionState": "new",
        "status": "discovering",
        "activity": [],
        "stages": engine._init_stages(),
    }


# ── Fix 1: human is never asked to pay an evidence provider ────────────


def test_discover_and_acquire_without_user_pay_fallback():
    _mongo()
    inv = _minimal_inv("inv_no_fallback")
    db.save_investigation(inv)

    state = asyncio.run(engine.discover_and_acquire("inv_no_fallback", "user_audit"))

    assert state["status"] in ("evidence_unavailable", "blocked")
    assert state["blockReason"], "a clear block reason must explain why evidence is unavailable"
    acquisitions = state.get("acquisitions") or []
    assert all(a.get("paymentState") != "payment_required" for a in acquisitions), (
        "no acquisition may ever ask the user to pay the provider")


def test_plan_acquisitions_never_emits_payment_required():
    _mongo()
    inv = _minimal_inv("inv_plan", question="Is this document genuine?")
    inv["evidenceRequirements"] = [{"id": "req1", "capability": "document_verification", "type": "document"}]
    db.save_investigation(inv)

    result = asyncio.run(gateway.plan_acquisitions("inv_plan", "user_audit"))
    assert result["acquisitions"] is not None
    assert all(a.get("paymentState") != "payment_required" for a in result["acquisitions"]), (
        "even the legacy planning path must never emit payment_required")


# ── Fix 2: provider-supplied independence is preserved ──────────────────


def test_make_evidence_item_preserves_independent():
    base = {"evidence_id": "ev1", "type": "url", "verdict": "supports", "confidence": 0.9}
    truly = engine._make_evidence_item({**base, "independent": True}, "url", "cap")
    assert truly["independent"] is True

    dependent = engine._make_evidence_item({**base, "independent": False}, "url", "cap")
    assert dependent["independent"] is False

    unknown = engine._make_evidence_item(base, "url", "cap")
    assert unknown["independent"] is None

    alias = engine._make_evidence_item({**base, "independence": False}, "url", "cap")
    assert alias["independent"] is False


# ── Fix 3: duplicate/dependent evidence is de-weighted ──────────────────


def _ev(eid, signal="supporting", confidence=90, independent=True):
    return {"id": eid, "signal": signal, "confidence": confidence,
            "finding": f"finding {eid}", "source": "Evidence Services (url)", "independent": independent}


def test_redundant_evidence_ids():
    inv = {"duplicates": {"duplicates": [["ev_a", "ev_b"], ["ev_a", "ev_c"]]}}
    evidence = [_ev("ev_a"), _ev("ev_b"), _ev("ev_c"), _ev("ev_d", independent=False)]
    redundant = analyze.redundant_evidence_ids(inv, evidence)
    assert redundant == {"ev_b", "ev_c", "ev_d"}  # ev_a kept primary; ev_d is provider-dependent

    inv2 = {"duplicates": [["ev_a", "ev_b"]]}
    assert analyze.redundant_evidence_ids(inv2, evidence) == {"ev_b", "ev_d"}

    assert analyze.redundant_evidence_ids({}, evidence) == {"ev_d"}  # no duplicate info


def test_heuristic_duplicates_not_double_counted():
    inv = {"duplicates": {"duplicates": [["ev_a", "ev_b"]]}}
    copy_a = _ev("ev_a")
    copy_b = _ev("ev_b")
    copy_b["finding"] = copy_a["finding"] = "same provider copy"
    result = analyze.heuristic_analysis(inv, [copy_a, copy_b])
    assert result["conclusion"] == "likely_genuine"
    assert result["conclusionText"].startswith("Based on 2 acquired evidence item(s), 1 supporting")
    assert any("de-weighted" in l for l in result["limitations"])


def test_heuristic_genuinely_independent_counts():
    result = analyze.heuristic_analysis({}, [_ev("ev_a"), _ev("ev_b")])
    assert result["conclusionText"].startswith("Based on 2 acquired evidence item(s), 2 supporting")
    assert not any("de-weighted" in l for l in result["limitations"])


def run():
    test_discover_and_acquire_without_user_pay_fallback()
    test_plan_acquisitions_never_emits_payment_required()
    test_make_evidence_item_preserves_independent()
    test_redundant_evidence_ids()
    test_heuristic_duplicates_not_double_counted()
    test_heuristic_genuinely_independent_counts()
    print("test_audit_fixes: all checks passed")


if __name__ == "__main__":
    run()