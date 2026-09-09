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


def _settled_amount_usdc(payment: dict) -> float:
    return round(float(payment.get("amount") or 0) * USDC_DECIMALS)


async def _spent_micro_for_investigation(investigation_id: str) -> float:
    return sum(
        _settled_amount_usdc(p)
        for p in db.get_payments_for_investigation(investigation_id)
        if p.get("status") == "settled"
    )


async def _total_spent_micro(user_id: str) -> float:
    """All-time settled spend for THIS user (never global across users)."""
    return sum(
        _settled_amount_usdc(p)
        for p in db.get_user_payments(user_id)
        if p.get("status") == "settled"
    )


def _session_start_iso() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=config.SESSION_BUDGET_WINDOW_HOURS)).isoformat()


async def _session_spent_micro(user_id: str) -> float:
    """Settled spend within the sliding session window (distinct from total)."""
    window_start = _session_start_iso()
    from datetime import datetime, timezone
    return sum(
        _settled_amount_usdc(p)
        for p in db.get_user_payments(user_id)
        if p.get("status") == "settled" and p.get("timestamp", "") >= window_start
    )


def _probe_x402_requirements(service: dict, transport=None) -> dict | None:
    """Probe a provider's resourceUrl for its authoritative PAYMENT-REQUIRED
    402 header: payTo, amount, network, asset. Returns None when the provider
    does not expose a parseable 402 (fail closed → provider_unavailable)."""
    import base64
    import json
    import httpx

    url = service.get("resourceUrl") or service.get("url")
    if not url or not str(url).lower().startswith("https://"):
        return None
    client = httpx.Client(timeout=6.0, transport=transport) if transport else httpx.Client(timeout=6.0)
    try:
        res = client.get(url)
        if res.status_code != 402:
            return None
        header = res.headers.get("payment-required") or res.headers.get("PAYMENT-REQUIRED")
        if not header:
            return None
        try:
            data = json.loads(base64.b64decode(header).decode("utf-8"))
        except Exception:
            data = json.loads(header)
        accepts = data.get("accepts") or []
        if not accepts:
            return None
        acc = accepts[0] if isinstance(accepts, list) else accepts
        pay_to = acc.get("payTo") or acc.get("pay_to")
        amount = acc.get("amount")
        asset = acc.get("asset") or acc.get("assetId") or service.get("assetId")
        network = acc.get("network") or data.get("network")
        if not pay_to or not amount:
            return None
        try:
            amount_micro = int(round(float(amount))) if float(amount) < 1e6 else int(amount)
        except (TypeError, ValueError):
            return None
        resource_url = data.get("resourceUrl") or service.get("resourceUrl")
        return {
            "payTo": pay_to,
            "amountMicro": amount_micro,
            "assetId": str(asset) if asset else None,
            "network": network,
            "scheme": acc.get("scheme", "exact"),
            "resourceUrl": resource_url,
        }
    except Exception:
        return None
    finally:
        client.close()


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
    session_spent = await _session_spent_micro(user_id)
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

        # Probe the provider's x402 endpoint for its authoritative payTo /
        # asset / amount before any payment is considered. No probe → no
        # purchase (fail closed; a provider we cannot verify against is never
        # paid). Downstream payments are server-side only (M2M, server wallet):
        # a budgeted acquisition can never become "the user pays the provider".
        reqs = _probe_x402_requirements(service)
        if not reqs:
            acquisitions.append({
                "id": _nanoid("acq"), "requirementId": requirement["id"],
                "investigationId": investigation_id, "serviceId": service["id"],
                "serviceName": service["name"], "capability": requirement["capability"],
                "amountMicro": service["priceMicro"], "assetId": service["assetId"],
                "resourceUrl": service["resourceUrl"], "network": service["network"],
                "paymentState": "provider_unavailable",
                "blockReason": "Provider did not expose x402 payment requirements",
                "updatedAt": _now_iso(),
            })
            emit_activity(inv, "blocked",
                          f"{service['name']}: could not verify x402 payment requirements",
                          requirement["capability"])
            continue

        ctx = {
            **prefs,
            "investigationSpent": inv_spent, "sessionSpent": session_spent, "totalSpent": total_spent,
        }
        b = budget.enforce_budget(reqs["amountMicro"], ctx)
        allowed = bool(b["allowed"])
        acquisition = {
            "id": _nanoid("acq"), "requirementId": requirement["id"], "investigationId": investigation_id,
            "serviceId": service["id"], "serviceName": service["name"],
            "capability": requirement["capability"], "amountMicro": reqs["amountMicro"],
            "assetId": reqs["assetId"] or service["assetId"], "resourceUrl": reqs["resourceUrl"] or service["resourceUrl"],
            "payTo": reqs["payTo"], "network": reqs["network"] or service["network"],
            # Fail closed: the human is never asked to pay a provider. Even a
            # budgeted acquisition resolves as evidence_unavailable because
            # downstream evidence is paid by Inquvia's server wallet (M2M) only.
            "paymentState": "evidence_unavailable",
            "blockReason": (None if allowed else budget.budget_block_reason(b["reason"])),
            "updatedAt": _now_iso(),
        }
        acquisitions.append(acquisition)
        if allowed:
            emit_activity(inv, "blocked",
                          f"{service['name']}: {reqs['amountMicro'] / USDC_DECIMALS:.4f} USDC would be "
                          "required but downstream providers are server-paid (M2M) only",
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
    """Legacy client-settled path — intentionally never produces purchases.

    Downstream evidence is paid by Inquvia's server wallet (M2M) only; the
    human is never asked to pay an evidence provider directly. This function
    is retained for backward compatibility and returns without creating any
    payable acquisition."""
    inv = db.get_investigation(investigation_id)
    if not inv:
        return {"ok": False, "error": "Investigation not found"}
    if inv.get("userId") and inv["userId"] != user_id:
        return {"ok": False, "error": "Forbidden"}
    return {"ok": True, "investigation": inv, "clientSettled": True}


async def record_acquisition(investigation_id: str, user_id: str, payload: dict, transport=None) -> dict:
    """Legacy client-settled acquisition recorder (dead path).

    The active flow never creates a payable acquisition, so nothing reachable
    calls this anymore: downstream evidence is paid by Inquvia server-side
    (M2M) and the human is never asked to pay a provider. Kept only so an
    orphaned client request cannot invent one: it still verifies any supplied
    settlement on-chain and never fabricates evidence or payments."""
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
    if acq.get("paymentState") in ("provider_unavailable", "payment_failed", "settlement_failed", "wallet_rejected"):
        return {"ok": False, "error": f"Acquisition not in a payable state ({acq.get('paymentState')})"}

    tx_id = payload.get("txId")
    if not tx_id:
        return {"ok": False, "error": "Missing payment transaction"}

    # Idempotent replay: an already-recorded settlement for this tx succeeds
    # without re-adding evidence or double-counting spend.
    existing = db.get_payment_by_settlement_ref(tx_id, user_id)
    if existing and existing.get("status") == "settled":
        return {"ok": True, "investigation": inv, "idempotent": True}

    # Verify settlement on-chain against the provider's requirements before
    # recording evidence.
    proof = await verify_settlement_on_chain(tx_id, transport=transport)
    checks = _settlement_checks(proof, acq)
    for key, ok in checks.items():
        if not ok:
            acq["paymentState"] = "settlement_failed"
            acq["blockReason"] = f"Settlement check failed: {key}"
            emit_activity(inv, "failed", f"Settlement not accepted ({key})", tx_id)
            db.save_investigation(inv)
            return {"ok": False, "error": f"Settlement rejected on-chain ({key})"}

    evidence_raw = payload.get("evidence") or {}
    if not evidence_raw:
        acq["paymentState"] = "settlement_failed"
        acq["blockReason"] = "No provider evidence returned"
        emit_activity(inv, "failed", "Provider did not return evidence", tx_id)
        db.save_investigation(inv)
        return {"ok": False, "error": "No evidence returned by provider"}

    acq["paymentState"] = "settled"
    acq["txId"] = proof.get("txId") or tx_id
    acq["payer"] = proof.get("sender")
    acq["updatedAt"] = _now_iso()

    db.save_payment({
        "id": _nanoid("pay"), "userId": user_id, "investigationId": inv["id"],
        "providerId": acq.get("serviceId") or acq.get("serviceName") or "unknown",
        "capability": acq.get("capability"), "amount": acq.get("amountMicro", 0) / USDC_DECIMALS,
        "currency": "USDC", "network": acq.get("network"), "protocol": "x402",
        "status": "settled", "settlementRef": acq["txId"], "timestamp": _now_iso(),
    })
    emit_activity(inv, "settlement_confirmed", f"Settlement confirmed on Algorand ({acq['txId'][:12]}...)", acq["txId"])

    evidence = normalize_evidence(acq, evidence_raw)
    evidence["paymentId"] = acq["txId"]
    evidence["acquisitionId"] = acq["id"]
    evidence["verificationStatus"] = "verified"
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


def _settlement_checks(proof: dict, acq: dict) -> dict:
    """Fail-closed checks: confirmed, axfer, USDC ASA, exact recipient, amount."""
    checks = {"confirmed": bool(proof.get("confirmed"))}
    if not checks["confirmed"]:
        return checks
    checks["asset_type"] = str(proof.get("type") or "") == "axfer"
    checks["asset_id"] = str(proof.get("assetId") or "") == str(acq.get("assetId") or "")
    checks["recipient"] = str(proof.get("receiver") or "") == str(acq.get("payTo") or "")
    checks["amount"] = int(proof.get("amount") or 0) >= int(acq.get("amountMicro") or 0)
    return checks


async def verify_settlement_on_chain(tx_id: str, transport=None) -> dict:
    """Verify a transaction is confirmed on-chain via Algod and return the
    full transfer facts (type, asset, receiver, sender, amount) so the caller
    can check receiver/asset/amount, not just confirmation."""
    import httpx
    url = f"{config.ALGOD_SERVER}/v2/transactions/pending/{tx_id}"
    headers = {"X-Algo-API-Token": config.ALGOD_TOKEN} if config.ALGOD_TOKEN else {}
    try:
        if transport:
            async with httpx.AsyncClient(timeout=8.0, transport=transport) as client:
                res = await client.get(url, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers=headers)
        if res.status_code == 200:
            data = res.json()
            confirmed_round = data.get("confirmed-round")
            if isinstance(confirmed_round, int) and confirmed_round > 0:
                txn = data.get("txn") or {}
                return {
                    "confirmed": True, "txId": tx_id, "confirmedRound": confirmed_round,
                    "type": txn.get("type"), "assetId": txn.get("xaid"),
                    "receiver": txn.get("arcv"), "sender": txn.get("asnd") or txn.get("snd"),
                    "amount": txn.get("aamt"),
                }
        return {"confirmed": False, "txId": tx_id}
    except Exception:
        return {"confirmed": False, "txId": tx_id}