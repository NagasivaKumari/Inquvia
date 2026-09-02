"""Evidence Acquisition Gateway — the single path to acquire external evidence.

Server side is authoritative for: discovery, budget enforcement, settlement
verification, evidence normalization, state transitions, and activity events
(mirrors gateway/index.ts).
"""
import secrets

from .. import db, config
from ..libraries import discovery, budget

USDC_DECIMALS = config.ALGORAND_USDC_DECIMALS


def _nanoid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)[:8]}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def emit_activity(inv, kind, label, detail=None):
    inv.setdefault("activity", []).append({
        "id": _nanoid("evt"),
        "investigationId": inv["id"],
        "userId": inv.get("userId"),
        "kind": kind,
        "label": label,
        "detail": detail,
        "createdAt": _now_iso(),
    })


async def _spent_micro_for_investigation(investigation_id: str) -> float:
    return sum(
        round(float(p.get("amount") or 0) * USDC_DECIMALS)
        for p in db.get_payments_for_investigation(investigation_id)
        if p.get("status") == "settled"
    )


async def _total_spent_micro(user_id: str) -> float:
    return sum(
        round(float(p.get("amount") or 0) * USDC_DECIMALS)
        for p in db.list_payments(10000)
        if p.get("status") == "settled"
    )


async def plan_acquisitions(investigation_id: str, user_id: str) -> dict:
    inv = db.get_investigation(investigation_id)
    if not inv:
        return {"okay": False, "acquisitions": [], "blockedReason": "Investigation not found"}
    user = db.get_user_by_id(user_id) if user_id else None
    requirements = inv.get("evidenceRequirements") or []

    if not requirements:
        return {"okay": True, "acquisitions": []}

    discovery_result = await discovery.discover_services(requirements)
    inv["discovery"] = discovery_result
    emit_activity(
        inv,
        "service_discovered",
        f"Discovered {len(discovery_result['services'])} evidence service(s)"
        if discovery_result["services"] else "No compatible evidence service discovered",
        discovery_result["source"],
    )

    prefs = (user or {}).get("paymentPrefs") or {
        "maxPerEvidenceCheck": 0.01, "maxPerInvestigation": 0.5,
        "sessionBudget": 5, "totalBudget": 50,
    }
    total_spent = await _total_spent_micro(user_id)
    session_spent = await _total_spent_micro(user_id)
    inv_spent = await _spent_micro_for_investigation(investigation_id)

    acquisitions = []
    for requirement in requirements:
        service = discovery.select_service_for_requirement(requirement, discovery_result["services"])

        if not service:
            acquisitions.append({
                "id": _nanoid("acq"), "requirementId": requirement["id"],
                "investigationId": investigation_id, "capability": requirement["capability"],
                "amountMicro": 0, "assetId": config.ALGORAND_USDC_ASA,
                "network": config.ALGORAND_NETWORK, "paymentState": "provider_unavailable",
                "blockReason": "No compatible evidence service discovered", "updatedAt": _now_iso(),
            })
            emit_activity(inv, "blocked",
                          f"No compatible evidence service for {requirement['capability']}",
                          requirement["capability"])
            continue

        ctx = {
            **prefs,
            "investigationSpent": inv_spent, "sessionSpent": session_spent, "totalSpent": total_spent,
        }
        b = budget.enforce_budget(service["priceMicro"], ctx)
        acquisition = {
            "id": _nanoid("acq"), "requirementId": requirement["id"], "investigationId": investigation_id,
            "serviceId": service["id"], "serviceName": service["name"],
            "capability": requirement["capability"], "amountMicro": service["priceMicro"],
            "assetId": service["assetId"], "network": config.ALGORAND_NETWORK,
            "paymentState": "payment_required" if b["allowed"] else "payment_failed",
            "blockReason": None if b["allowed"] else budget.budget_block_reason(b["reason"]),
            "updatedAt": _now_iso(),
        }
        acquisitions.append(acquisition)
        if b["allowed"]:
            emit_activity(inv, "payment_required",
                          f"{service['name']}: {(service['priceMicro'] / USDC_DECIMALS):.4f} USDC required",
                          requirement["capability"])
        else:
            emit_activity(inv, "blocked", "Evidence check blocked by budget limit", b["reason"])

    inv["acquisitions"] = acquisitions
    db.save_investigation(inv)
    return {"okay": True, "acquisitions": acquisitions}


def normalize_evidence(acquisition, raw) -> dict:
    data = raw or {}
    meta = data.get("metadata") or data.get("evidence") or {}
    if isinstance(data.get("finding"), str):
        text = data["finding"]
    elif isinstance(meta, dict) and isinstance(meta.get("summary"), str):
        text = meta["summary"]
    else:
        text = ""
    cap = acquisition.get("capability") or ""
    if "image" in cap:
        etype = "image"
    elif "video" in cap:
        etype = "video"
    elif "document" in cap:
        etype = "document"
    elif "url" in cap or "domain" in cap:
        etype = "url"
    else:
        etype = "text"
    confidence = 0
    if isinstance(meta, dict) and isinstance(meta.get("confidence"), (int, float)):
        raw_conf = meta["confidence"]
        confidence = clamp_conf(round(float(raw_conf)))
    signal = meta.get("signal") if isinstance(meta, dict) and meta.get("signal") in ("supporting", "contradictory") else "uncertain"
    return {
        "id": _nanoid("ev"), "type": etype,
        "source": acquisition.get("serviceName") or acquisition.get("serviceId") or "External evidence service",
        "timestamp": _now_iso(),
        "finding": text or f"Evidence acquired from {acquisition.get('serviceName') or 'external service'}",
        "confidence": confidence,
        "status": "collected",
        "cost": (acquisition.get("amountMicro") or 0) / USDC_DECIMALS,
        "signal": signal,
        "capability": cap,
        "acquisitionId": acquisition.get("id"),
        "paymentId": acquisition.get("txId"),
        "verificationStatus": "unverified",
        "metadata": meta,
    }


def clamp_conf(v):
    if v is None or not isinstance(v, (int, float)):
        return 0
    return min(100, max(0, round(v)))


def create_investigation_record(input_: dict) -> dict:
    now = _now_iso()
    return {
        "id": input_["id"], "userId": input_.get("userId"), "title": input_["title"],
        "capability": input_.get("capability"), "capabilityPriceUsdc": input_.get("capabilityPriceUsdc"),
        "idempotencyKey": input_.get("idempotencyKey"), "question": input_["question"],
        "inputs": input_.get("inputs") or [], "inputType": input_.get("inputType"),
        "investigationPlan": [], "selectedCapabilities": [], "evidence": [],
        "contradictions": [], "conclusion": "inconclusive", "conclusionText": "",
        "confidence": 0, "risk": "unknown", "limitations": [],
        "economicSummary": {"totalSpend": 0, "checksPurchased": 0, "providerCategories": [], "settlementStatus": "Pending"},
        "status": input_.get("status"), "stages": [], "createdAt": now, "updatedAt": now,
        "findings": [], "supportingEvidenceIds": [], "contradictoryEvidenceIds": [],
        "evidenceRequirements": [], "acquisitions": [], "activity": [],
        "evidenceGraph": {"nodes": [], "edges": []},
    }


async def acquire_downstream(investigation_id: str, user_id: str) -> dict:
    """Server-wallet downstream acquisition (mirrors gateway/index.ts). Only
    active when SERVER_WALLET_MNEMONIC is configured; otherwise reports the
    server wallet as unconfigured rather than fabricating evidence."""
    inv = db.get_investigation(investigation_id)
    if not inv:
        return {"ok": False, "error": "Investigation not found"}
    if inv.get("userId") and inv["userId"] != user_id:
        return {"ok": False, "error": "Forbidden"}
    if not config.SERVER_WALLET_MNEMONIC:
        return {"ok": False, "error": "Server wallet not configured"}

    pending = [a for a in (inv.get("acquisitions") or []) if a.get("paymentState") == "payment_required"]
    if not pending:
        return {"ok": True, "investigation": inv}

    # ponytail: server-wallet x402 client (sign + facilitator settle) is not
    # implemented in the Python port; user pays client-side. Downstream only
    # resolves via acquireEvidenceServerSide in Node. Mark unavailable.
    for acq in pending:
        acq["paymentState"] = "provider_unavailable"
        acq["blockReason"] = "No payable server-side endpoint available in Python port"
    db.save_investigation(inv)
    return {"ok": True, "investigation": inv}


def record_acquisition(investigation_id: str, user_id: str, payload: dict) -> dict:
    """Record a client-settled acquisition (mirrors gateway/index.ts)."""
    inv = db.get_investigation(investigation_id)
    if not inv:
        return {"ok": False, "error": "Investigation not found"}
    if inv.get("userId") and inv["userId"] != user_id:
        return {"ok": False, "error": "Forbidden"}
    acq = next((a for a in inv.get("acquisitions") or [] if a.get("id") == payload.get("acquisitionId")), None)
    if not acq:
        return {"ok": False, "error": "Acquisition not found"}

    if acq.get("paymentState") in ("evidence_received", "settled"):
        return {"ok": True, "investigation": inv}
    if acq.get("paymentState") in ("provider_unavailable", "payment_failed", "settlement_failed"):
        return {"ok": False, "error": f"Acquisition not in a payable state ({acq.get('paymentState')})"}

    tx_id = payload.get("txId")
    if not tx_id:
        return {"ok": False, "error": "Missing payment transaction"}

    # Verify settlement on-chain against Algod before recording evidence.
    proof = verify_settlement_on_chain(tx_id)
    if not proof.get("confirmed"):
        acq["paymentState"] = "settlement_failed"
        acq["blockReason"] = "Settlement could not be verified on-chain"
        emit_activity(inv, "failed", "Settlement could not be verified on-chain", acq.get("txId"))
        db.save_investigation(inv)
        return {"ok": False, "error": "Settlement not confirmed on Algorand"}

    acq["paymentState"] = "settled"
    acq["txId"] = proof.get("txId") or tx_id
    acq["updatedAt"] = _now_iso()

    db.save_payment({
        "id": _nanoid("pay"), "userId": user_id, "investigationId": inv["id"],
        "providerId": acq.get("serviceId") or acq.get("serviceName") or "unknown",
        "capability": acq.get("capability"), "amount": acq.get("amountMicro", 0) / USDC_DECIMALS,
        "currency": "USDC", "network": acq.get("network"), "protocol": "x402",
        "status": "settled", "settlementRef": acq["txId"], "timestamp": _now_iso(),
    })
    emit_activity(inv, "settlement_confirmed", f"Settlement confirmed on Algorand ({acq['txId'][:12]}...)", acq["txId"])

    evidence = normalize_evidence(acq, payload.get("evidence") or {})
    evidence["paymentId"] = acq["txId"]
    evidence["acquisitionId"] = acq["id"]
    acq["evidence"] = evidence
    inv.setdefault("evidence", [])
    if not any(e["id"] == evidence["id"] for e in inv["evidence"]):
        inv["evidence"].append(evidence)
    acq["paymentState"] = "evidence_received"
    emit_activity(inv, "evidence_received",
                  f"Evidence received from {acq.get('serviceName') or 'external service'}",
                  acq.get("capability"))

    db.save_investigation(inv)
    return {"ok": True, "investigation": inv}


async def verify_settlement_on_chain(tx_id: str) -> dict:
    """Verify a transaction is confirmed on-chain via Algod."""
    import httpx
    url = f"{config.ALGOD_SERVER}/v2/transactions/pending/{tx_id}"
    headers = {"X-Algo-API-Token": config.ALGOD_TOKEN} if config.ALGOD_TOKEN else {}
    try:
        async with httpx.Client(timeout=8.0) as client:
            res = await client.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            confirmed_round = data.get("confirmed-round")
            if isinstance(confirmed_round, int) and confirmed_round > 0:
                return {"confirmed": True, "txId": tx_id, "confirmedRound": confirmed_round}
        return {"confirmed": False, "txId": tx_id}
    except Exception:
        return {"confirmed": False, "txId": tx_id}