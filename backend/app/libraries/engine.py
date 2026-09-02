"""Investigation engine (mirrors investigation/engine.ts)."""
import asyncio
import secrets

from .. import db, config
from ..libraries import gateway as gateway_mod
from ..libraries.analyze import heuristic_analysis, build_evidence_graph
from ..libraries import analyzers

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS

RESOLVED_STATES = [
    "evidence_received", "settled", "provider_unavailable", "payment_failed",
    "settlement_failed", "wallet_rejected", "unsupported_network",
    "insufficient_balance", "evidence_request_failed",
]


def _nanoid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)[:8]}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def detect_input_type(inputs: list[dict]) -> str:
    types = {i.get("type") for i in inputs}
    if len(types) > 1:
        return "mixed"
    return inputs[0]["type"] if inputs and inputs[0].get("type") else "text"


def _set_stage(inv, stage_id, status):
    for s in inv.get("stages") or []:
        if s["id"] == stage_id:
            s["status"] = status


def _init_stages() -> list[dict]:
    return [{"id": s["id"], "label": s["label"], "status": "pending"} for s in config.INVESTIGATION_STAGES]


def _emit(inv, kind, label, detail=None):
    inv.setdefault("activity", []).append({
        "id": _nanoid("evt"), "investigationId": inv["id"], "userId": inv.get("userId"),
        "kind": kind, "label": label, "detail": detail, "createdAt": _now_iso(),
    })


def start_capability_investigation(input_: dict) -> dict:
    cap = config.get_paid_capability(input_.get("capability") or "")
    inv = gateway_mod.create_investigation_record({
        "id": input_["id"], "userId": input_.get("userId"),
        "title": input_.get("title") or (cap["title"] if cap else "Investigation in Progress"),
        "question": input_["question"], "inputs": input_.get("inputs") or [],
        "inputType": detect_input_type(input_.get("inputs") or []),
        "status": "created",
        "capability": input_.get("capability"),
        "capabilityPriceUsdc": cap.get("priceUsdc") if cap else None,
        "idempotencyKey": input_.get("idempotencyKey"),
    })
    inv["stages"] = _init_stages()
    _emit(inv, "investigation_created", f"{(cap['title'] if cap else 'Capability')} investigation started")
    db.save_investigation(inv)
    return db.get_investigation(inv["id"])


def plan_capability(inv: dict, requirements: list[dict]) -> dict:
    inv2 = db.get_investigation(inv["id"])
    inv2["status"] = "planning"
    _set_stage(inv2, "planning", "active")
    db.save_investigation(inv2)
    inv2["evidenceRequirements"] = requirements or []
    inv2["investigationPlan"] = [
        {"id": r["id"], "capability": r["capability"], "reason": r["reason"],
         "estimatedCost": 0, "expectedValue": 0, "status": "pending"}
        for r in (requirements or [])
    ]
    _set_stage(inv2, "planning", "completed")
    inv2["status"] = "discovering"
    inv2["updatedAt"] = _now_iso()
    db.save_investigation(inv2)
    return db.get_investigation(inv2["id"])


async def await_finalize_investigation(id, analyze=None) -> dict:
    """Async wrapper around finalize (analyzers are async)."""
    inv = db.get_investigation(id)
    if not inv:
        raise ValueError("Investigation not found")

    acqs = inv.get("acquisitions") or []
    unresolved = [a for a in acqs if a.get("paymentState") not in RESOLVED_STATES]
    if unresolved:
        return inv

    evidence = [e for e in (inv.get("evidence") or []) if e.get("status") == "collected"]
    analyzer = analyze or analyzers.get_analyzer(inv.get("capability")) or heuristic_analysis

    if not evidence and not analyzers.get_analyzer(inv.get("capability")):
        inv["status"] = "evidence_unavailable"
        inv["conclusion"] = "insufficient_evidence"
        inv["conclusionText"] = (
            "Insufficient evidence was acquired to render an assessment. The investigation could not be "
            "completed because no paid external evidence was obtained."
        )
        inv["confidence"] = 0
        inv["limitations"] = [
            "No external evidence was successfully acquired",
            inv.get("blockReason") or "Evidence acquisition did not complete",
        ]
        inv["updatedAt"] = _now_iso()
        db.save_investigation(inv)
        return inv

    inv["status"] = "analyzing"
    _set_stage(inv, "analyzing", "active")
    db.save_investigation(inv)

    if asyncio.iscoroutinefunction(analyzer):
        result = await analyzer(inv, evidence)
    else:
        result = analyzer(inv, evidence)

    inv["status"] = "cross_checking"
    _set_stage(inv, "analyzing", "completed")
    _set_stage(inv, "cross_checking", "active")
    inv["supportingEvidenceIds"] = [
        e["id"] for e in evidence if e.get("signal") == "supporting" or e.get("supportsClaim")
    ]
    inv["contradictoryEvidenceIds"] = [
        e["id"] for e in evidence if e.get("signal") == "contradictory" or e.get("contradictsClaim")
    ]
    _emit(inv, "cross_check_completed", "Cross-check of acquired evidence completed")
    db.save_investigation(inv)

    inv["conclusion"] = result["conclusion"]
    inv["conclusionText"] = result["conclusionText"]
    inv["confidence"] = result["confidence"]
    inv["risk"] = result["risk"]
    inv["findings"] = result["findings"]
    inv["limitations"] = result["limitations"]
    inv["contradictions"] = result["contradictions"]
    inv["sourcesUsed"] = (
        result.get("sourcesUsed") if result.get("sourcesUsed") else [e.get("source") for e in evidence]
    )
    if result.get("uncertainty"):
        inv["uncertainty"] = result["uncertainty"]
    inv["evidenceGraph"] = build_evidence_graph(inv, evidence)
    inv["economicSummary"] = {
        "totalSpend": sum(
            a.get("amountMicro", 0) / USDC_DECIMALS
            for a in acqs if a.get("paymentState") in ("evidence_received", "settled")
        ),
        "checksPurchased": len([a for a in acqs if a.get("evidence")]),
        "providerCategories": list(dict.fromkeys(a.get("capability") for a in acqs if a.get("evidence"))),
        "settlementStatus": "Settled",
        "algorandRef": next((a.get("txId") for a in acqs if a.get("txId")), None),
    }
    inv["status"] = "completed"
    _set_stage(inv, "cross_checking", "completed")
    _set_stage(inv, "assessment", "completed")
    inv["currentStage"] = None
    inv["updatedAt"] = _now_iso()
    _emit(inv, "assessment_generated", "Assessment generated for capability investigation")
    db.save_investigation(inv)
    return inv


async def discover_and_acquire(investigation_id: str, user_id: str) -> dict:
    inv2 = db.get_investigation(investigation_id)
    if not inv2:
        raise ValueError("Investigation not found")

    _set_stage(inv2, "discovering", "active")
    db.save_investigation(inv2)

    plan = await gateway_mod.plan_acquisitions(investigation_id, user_id)
    inv2 = db.get_investigation(investigation_id)
    inv2["acquisitions"] = plan["acquisitions"]
    _set_stage(inv2, "discovering", "completed")

    pending = [a for a in plan["acquisitions"] if a.get("paymentState") == "payment_required"]

    if pending:
        if config.SERVER_WALLET_MNEMONIC:
            await gateway_mod.acquire_downstream(investigation_id, user_id)
            return await await_finalize_investigation(investigation_id)
        inv2["status"] = "awaiting_payment"
        _set_stage(inv2, "awaiting_payment", "active")
        inv2["updatedAt"] = _now_iso()
        db.save_investigation(inv2)
        return inv2

    return await await_finalize_investigation(investigation_id)


async def run_investigation(request: dict) -> dict:
    id_ = request.get("id") or f"case_{secrets.token_urlsafe(6)[:10]}"
    inv = db.get_investigation(id_)
    if not inv:
        inv = gateway_mod.create_investigation_record({
            "id": id_, "userId": request.get("userId"), "title": "Investigation in Progress",
            "question": request.get("question", ""), "inputs": request.get("inputs") or [],
            "inputType": detect_input_type(request.get("inputs") or []), "status": "created",
        })
        inv["stages"] = _init_stages()
        db.save_investigation(inv)
        _emit(inv, "investigation_created", "Investigation created")

    if inv["status"] in ("created", "planning"):
        from ..libraries.planner import plan_evidence_requirements
        requirements = plan_evidence_requirements(
            inv.get("question", ""), [i.get("type") for i in (inv.get("inputs") or [])]
        )
        inv = plan_capability(inv, requirements)

    if inv["status"] == "discovering":
        inv = await discover_and_acquire(id_, request.get("userId") or "")

    return db.get_investigation(id_)


def get_investigation_progress(id) -> dict | None:
    return db.get_investigation(id)