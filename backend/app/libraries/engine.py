"""Investigation engine (mirrors investigation/engine.ts)."""
import asyncio
import logging
import secrets

from .. import db, config
from ..libraries import gateway as gateway_mod
from ..libraries.analyze import heuristic_analysis, build_evidence_graph
from ..libraries import analyzers

logger = logging.getLogger(__name__)

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS

RESOLVED_STATES = [
    "evidence_received", "settled", "evidence_unavailable", "provider_unavailable", "payment_failed",
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


async def await_finalize_investigation(id, analyze=None, allow_input_analysis=False) -> dict:
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

    if not evidence and not allow_input_analysis:
        # Zero acquired external evidence → NO verdict, regardless of analyzer.
        # Capability analyzers exist for every capability; they must never run
        # on an empty evidence set (that produced fabricated assessments).
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
    if not inv.get("evidenceGraph") or not (inv["evidenceGraph"].get("nodes") or inv["evidenceGraph"].get("edges")):
        inv["evidenceGraph"] = build_evidence_graph(inv, evidence)
    inv_payments = db.get_payments_for_investigation(inv["id"])
    capability_fee = sum(
        float(p.get("amount") or 0)
        for p in inv_payments if p.get("status") == "settled" and p.get("capability") == inv.get("capability")
    )
    inv["economicSummary"] = {
        "totalSpend": round(capability_fee, 6),
        "capabilityFeeUsdc": round(capability_fee, 6),
        "checksPurchased": len([a for a in acqs if a.get("evidence")]),
        "providerCategories": list(dict.fromkeys(a.get("capability") for a in acqs if a.get("evidence"))),
        "settlementStatus": "Settled",
        "algorandRef": next((a.get("txId") for a in acqs if a.get("txId")), None),
        "paymentReferences": [p.get("settlementRef") for p in inv_payments
                              if p.get("status") == "settled" and p.get("settlementRef")],
    }

    # Evidence reasoning: classify roles, duplicates, stale, independent,
    # missing types, and surface relationships in the final result.
    plan_types = {r.get("capability") or r.get("type")
                  for r in (inv.get("evidenceRequirements") or [])}
    acquired_types = {e.get("type") or e.get("capability") for e in evidence}
    missing_types = sorted(plan_types - acquired_types)
    classification = _classify_evidence(
        evidence, inv.get("duplicates"), missing_types)
    inv["evidenceClassification"] = classification

    # Aggregate relationships from provider metadata (never fabricated).
    rel_seen = set()
    rel_agg = []
    for e in evidence:
        for r in (e.get("relationships") or []):
            key = tuple(sorted(r.items())) if isinstance(r, dict) else str(r)
            if key not in rel_seen:
                rel_seen.add(key)
                rel_agg.append(r)

    inv["finalResult"] = {
        "decision": result["conclusion"],
        "conclusionText": result["conclusionText"],
        "confidence": result["confidence"],
        "supportingEvidenceIds": [e["id"] for e in evidence if e.get("signal") == "supporting"],
        "contradictoryEvidenceIds": [e["id"] for e in evidence if e.get("signal") == "contradictory"],
        "uncertainEvidenceIds": [e["id"] for e in evidence if e.get("signal") == "uncertain"],
        "evidenceCount": len(evidence),
        "relationships": rel_agg,
        "missingEvidenceTypes": missing_types,
        "paymentReferences": inv["economicSummary"]["paymentReferences"],
        "limitations": result.get("limitations") or [],
        "independenceNote": classification["independenceNote"],
        "assurance": "Assessment is evidence-based, not a guarantee of truth.",
    }

    inv["status"] = "completed"
    _set_stage(inv, "cross_checking", "completed")
    _set_stage(inv, "assessment", "completed")
    inv["currentStage"] = None
    inv["updatedAt"] = _now_iso()
    _emit(inv, "assessment_generated", "Assessment generated for capability investigation")
    db.save_investigation(inv)
    return inv


async def analyze_investigation(investigation_id: str) -> dict:
    """Analyze the user's submitted input with Inquvia's own analyzers."""
    inv = db.get_investigation(investigation_id)
    if not inv:
        raise ValueError("Investigation not found")

    _set_stage(inv, "discovering", "completed")
    _set_stage(inv, "evidence_requested", "completed")
    _set_stage(inv, "evidence_received", "completed")
    _emit(inv, "internal_analysis_started", "Analyzing submitted data with Inquvia tools")
    inv["status"] = "analyzing"

    # Create internal evidence entries from submitted inputs so the report can
    # display meaningful evidence count, source nodes in the graph, and the AI
    # analyzer has items to reason over instead of an empty evidence list.
    from ..libraries import storage as _storage
    existing_ev_sources = {e.get("metadata", {}).get("origin") for e in (inv.get("evidence") or [])}
    if "user_submission" not in existing_ev_sources:
        for inp in inv.get("inputs") or []:
            content_preview = inp.get("content") or inp.get("fileName") or "submitted input"
            text_content = None
            if inp.get("filePath"):
                text_content = _storage.read_stored_text(inp["filePath"], 500)
            finding_text = (text_content[:200].strip() if text_content else f"User-submitted {content_preview}")
            ev_item = {
                "id": _nanoid("ev"),
                "type": inp.get("type", "document"),
                "source": f"Submitted {inp.get('type', 'input')}: {content_preview}",
                "finding": finding_text,
                "signal": "uncertain",
                "status": "collected",
                "confidence": None,
                "timestamp": _now_iso(),
                "metadata": {
                    "origin": "user_submission",
                    "fileName": inp.get("fileName") or inp.get("content"),
                    "inputType": inp.get("type"),
                },
            }
            inv.setdefault("evidence", []).append(ev_item)

    db.save_investigation(inv)
    return await await_finalize_investigation(investigation_id, allow_input_analysis=True)



def _classify_evidence(evidence: list[dict], duplicates, missing_types: list[str]) -> dict:
    """Classify evidence roles without fabricating conclusions.

    signal and confidence come from the provider's EvidenceResponse; duplicate
    pairs come from the provider's duplicates analysis when present; stale is
    a local age check; independence is only asserted when a provider analysis
    says so (otherwise reported as unknown).
    """
    import json as _json
    from datetime import datetime, timezone

    pairs = {}
    try:
        raw = duplicates or {}
        pair_list = raw.get("duplicates") if isinstance(raw, dict) else raw
        for p in pair_list or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pairs.setdefault(p[0], []).append(p[1])
                pairs.setdefault(p[1], []).append(p[0])
    except Exception:
        pairs = {}

    now = datetime.now(timezone.utc)
    items = []
    for e in evidence:
        ts = None
        try:
            ts = datetime.fromisoformat((e.get("timestamp") or "").replace("Z", "+00:00"))
        except Exception:
            ts = None
        stale = bool(ts and (now - ts).days > 30)
        conf = e.get("confidence") or 0
        items.append({
            "id": e["id"],
            "type": e.get("type"),
            "signal": e.get("signal") or "uncertain",
            "nonProbative": bool(conf < 20 or not e.get("finding")),
            "stale": stale,
            "duplicates": pairs.get(e["id"], []),
            "independent": e.get("independent") if e.get("independent") is not None else None,
            "source": e.get("source"),
            "relationships": e.get("relationships") or [],
        })

    any_duplicate = bool(pairs)
    return {
        "items": items,
        "missing": sorted(set(missing_types)),
        "duplicatePairsFound": any_duplicate,
        "independenceNote": (
            "Independence is counted only when explicitly declared by the provider; "
            "missing declarations remain unknown."
        ),
    }



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
        inv = await analyze_investigation(id_)

    return db.get_investigation(id_)


def get_investigation_progress(id) -> dict | None:
    return db.get_investigation(id)