"""Investigation engine (mirrors investigation/engine.ts)."""
import asyncio
import secrets

from .. import db, config
from ..libraries import gateway as gateway_mod
from ..libraries.analyze import heuristic_analysis, build_evidence_graph
from ..libraries import analyzers, evidence_client, storage

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

    if not evidence:
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
    downstream_spend = sum(
        float(p.get("amount") or 0)
        for p in inv_payments if p.get("status") == "settled" and p.get("capability") != inv.get("capability")
    )
    inv["economicSummary"] = {
        "totalSpend": round(capability_fee + downstream_spend, 6),
        "capabilityFeeUsdc": round(capability_fee, 6),
        "downstreamSpendUsdc": round(downstream_spend, 6),
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


async def acquire_from_evidence_services(inv: dict) -> list[dict]:
    """Call deployed Evidence Services endpoints via HTTP for each input in the investigation."""
    if not evidence_client.is_configured():
        return []

    question = inv.get("question") or ""
    inputs = inv.get("inputs") or []
    capability = inv.get("capability") or ""
    collected = []

    for inp in inputs:
        itype = inp.get("type")
        content = inp.get("content") or ""
        file_path = inp.get("filePath")
        file_bytes = None
        if file_path:
            p = storage.resolve_stored_path(file_path)
            if p and p.is_file():
                try:
                    file_bytes = p.read_bytes()
                except Exception:
                    file_bytes = None

        raw_resp = None
        if itype == "url" or (not itype and content.startswith(("http://", "https://"))):
            raw_resp = await evidence_client.acquire_url_evidence(content, claim=question)
        elif itype == "image" and file_bytes:
            raw_resp = await evidence_client.acquire_image_evidence(
                file_bytes, inp.get("fileName") or "image.jpg", inp.get("mimeType") or "image/jpeg", claim=question
            )
        elif itype == "video" and file_bytes:
            raw_resp = await evidence_client.acquire_video_evidence(
                file_bytes, inp.get("fileName") or "video.mp4", inp.get("mimeType") or "video/mp4", claim=question
            )
        elif itype == "document" and file_bytes:
            raw_resp = await evidence_client.acquire_document_evidence(
                file_bytes, inp.get("fileName") or "document.pdf", inp.get("mimeType") or "application/pdf", claim=question
            )
        elif itype == "data":
            raw_resp = await evidence_client.acquire_structured_evidence(
                file_bytes=file_bytes,
                filename=inp.get("fileName"),
                mime=inp.get("mimeType"),
                payload_json=content if not file_bytes else None,
                claim=question,
            )
        elif itype == "text":
            raw_resp = await evidence_client.acquire_structured_evidence(
                payload_json=None,
                claim=content or question,
            )

        if raw_resp:
            verdict = raw_resp.get("verdict") or "insufficient_evidence"
            signal = "supporting" if verdict == "supports" else ("contradictory" if verdict == "contradicts" else "uncertain")
            conf_val = raw_resp.get("confidence", 0)
            conf = round(conf_val * 100) if isinstance(conf_val, (int, float)) and conf_val <= 1.0 else round(float(conf_val or 0))

            obs = raw_resp.get("observations") or []
            facts = raw_resp.get("facts") or []
            if obs:
                finding = "; ".join(o.get("text", "") for o in obs[:3] if o.get("text"))
            elif facts:
                finding = "; ".join(f.get("text", "") for f in facts[:3] if f.get("text"))
            else:
                finding = f"Evidence processed for {raw_resp.get('type') or itype} ({verdict})"

            ev_item = {
                "id": raw_resp.get("evidence_id") or _nanoid("ev"),
                "type": raw_resp.get("type") or itype or "text",
                "source": f"Evidence Services ({raw_resp.get('type') or itype})",
                "timestamp": _now_iso(),
                "finding": finding,
                "confidence": min(100, max(0, conf)),
                "status": "collected",
                "cost": 0.0,
                "signal": signal,
                "capability": raw_resp.get("type") or capability or itype,
                "verificationStatus": "verified",
                "metadata": raw_resp,
            }
            collected.append(ev_item)

    # Multi-modal synthesis when multiple evidence pieces are present
    if len(collected) >= 2:
        try:
            cm_resp = await evidence_client.call_cross_modal(collected, claim=question)
            if cm_resp:
                inv["crossModalAnalysis"] = cm_resp
                if cm_resp.get("contradictions"):
                    inv.setdefault("contradictions", []).extend(cm_resp["contradictions"])
        except Exception:
            pass

        try:
            prov_resp = await evidence_client.call_provenance(collected)
            if prov_resp and prov_resp.get("graph"):
                inv["evidenceGraph"] = prov_resp.get("graph")
                inv["provenance"] = prov_resp
        except Exception:
            pass

    # Timeline synthesis if timestamp entries exist
    has_timestamps = any(e.get("metadata", {}).get("timestamps") for e in collected)
    if has_timestamps or len(collected) >= 2:
        try:
            tl_resp = await evidence_client.call_timeline(collected, claim=question)
            if tl_resp and tl_resp.get("events"):
                inv["timeline"] = tl_resp.get("events")
        except Exception:
            pass

    return collected


async def discover_and_acquire(investigation_id: str, user_id: str) -> dict:
    inv2 = db.get_investigation(investigation_id)
    if not inv2:
        raise ValueError("Investigation not found")

    _set_stage(inv2, "discovering", "active")
    db.save_investigation(inv2)

    # 1. Primary: Use deployed Evidence Services if configured
    if evidence_client.is_configured():
        _emit(inv2, "evidence_requested", "Requesting evidence from deployed Evidence Services")
        _set_stage(inv2, "evidence_requested", "active")
        ev_items = await acquire_from_evidence_services(inv2)
        if ev_items:
            inv2.setdefault("evidence", [])
            for ev in ev_items:
                if not any(e.get("id") == ev["id"] for e in inv2["evidence"]):
                    inv2["evidence"].append(ev)
                inv2.setdefault("acquisitions", []).append({
                    "id": _nanoid("acq"),
                    "serviceId": "evidence-services",
                    "serviceName": "Deployed Evidence Services",
                    "capability": ev.get("capability"),
                    "paymentState": "evidence_received",
                    "evidence": ev,
                })
            _set_stage(inv2, "discovering", "completed")
            _set_stage(inv2, "evidence_requested", "completed")
            _set_stage(inv2, "evidence_received", "completed")
            _emit(inv2, "evidence_received", f"Received {len(ev_items)} evidence package(s) from Evidence Services")
            db.save_investigation(inv2)
            return await await_finalize_investigation(investigation_id)

    # 2. Fallback: Query gateway discovery plan if Evidence Services returned nothing or is not configured
    plan = await gateway_mod.plan_acquisitions(investigation_id, user_id)
    inv2 = db.get_investigation(investigation_id)
    inv2["acquisitions"] = plan["acquisitions"]
    _set_stage(inv2, "discovering", "completed")

    pending = [a for a in plan["acquisitions"] if a.get("paymentState") == "payment_required"]

    if pending:
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