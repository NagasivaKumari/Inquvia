"""Investigation engine (mirrors investigation/engine.ts)."""
import asyncio
import logging
import secrets

from .. import db, config
from ..libraries import gateway as gateway_mod
from ..libraries.analyze import heuristic_analysis, build_evidence_graph
from ..libraries import analyzers, evidence_client, storage

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
        "paymentReferences": [p.get("settlementRef") for p in inv_payments
                              if p.get("status") == "settled" and p.get("settlementRef")],
        "downstreamPaymentRefs": [p.get("settlementRef") for p in inv_payments
                                  if p.get("status") == "settled" and p.get("settlementRef")
                                  and p.get("capability") != inv.get("capability")],
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
        "totalDownstreamCostUsdc": round(downstream_spend, 6),
        "downstreamPaymentRefs": inv["economicSummary"]["downstreamPaymentRefs"],
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


def _build_budget_context(user_id: str, investigation_id: str) -> dict:
    """Build a budget enforcement context from the user's prefs and current spend."""
    user = db.get_user_by_id(user_id) if user_id else None
    prefs = (user or {}).get("paymentPrefs") or config.DEFAULT_PAYMENT_PREFS
    # Spend totals are filled in by _update_budget_spends (async)
    return {
        **prefs,
        "investigationSpent": 0,
        "sessionSpent": 0,
        "totalSpent": 0,
    }


async def _update_budget_spends(ctx: dict, user_id: str, investigation_id: str) -> dict:
    """Refresh the spend totals in a budget context dict."""
    from . import gateway as gw
    if user_id:
        ctx["totalSpent"] = await gw._total_spent_micro(user_id)
        ctx["sessionSpent"] = await gw._session_spent_micro(user_id)
    if investigation_id:
        ctx["investigationSpent"] = await gw._spent_micro_for_investigation(investigation_id)
    return ctx


def _required_input_types(inv: dict) -> set:
    """Determine which evidence input types this investigation needs.

    Combines the planner's evidenceRequirements (from the plan the engine
    stored) with the actual input types present, so the provider is called
    selectively rather than for every endpoint.
    """
    required = set()
    for inp in inv.get("inputs") or []:
        t = inp.get("type")
        if not t and (inp.get("content") or "").startswith(("http://", "https://")):
            t = "url"
        if t:
            required.add(t)
    for req in (inv.get("plan") or []) + (inv.get("evidenceRequirements") or []):
        req_type = req.get("type") or req.get("capability") or ""
        if req_type:
            required.add(req_type)
    return required


def _call_input_evidence(itype: str, inp: dict, question: str,
                         budget_ctx: dict | None,
                         provider_url: str | None = None) -> dict | None:
    """Route a single input to the matching deployed evidence endpoint."""
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
    fname = inp.get("fileName")
    mime = inp.get("mimeType")

    if itype == "url":
        return evidence_client.acquire_url_evidence(content, claim=question, budget_ctx=budget_ctx, base_url=provider_url)
    if itype == "image":
        return evidence_client.acquire_image_evidence(
            file_bytes or b"", fname or "image.jpg", mime or "image/jpeg",
            claim=question, budget_ctx=budget_ctx, base_url=provider_url)
    if itype == "video":
        return evidence_client.acquire_video_evidence(
            file_bytes or b"", fname or "video.mp4", mime or "video/mp4",
            claim=question, budget_ctx=budget_ctx, base_url=provider_url)
    if itype == "document":
        return evidence_client.acquire_document_evidence(
            file_bytes or b"", fname or "document.pdf", mime or "application/pdf",
            claim=question, budget_ctx=budget_ctx, base_url=provider_url)
    if itype == "audio":
        return evidence_client.acquire_audio_evidence(
            file_bytes or b"", fname or "audio.mp3", mime or "audio/mpeg",
            claim=question, budget_ctx=budget_ctx, base_url=provider_url)
    # data / text / structured
    return evidence_client.acquire_structured_evidence(
        file_bytes=file_bytes, filename=fname, mime=mime,
        payload_json=content if not file_bytes else None,
        claim=content or question, budget_ctx=budget_ctx, base_url=provider_url)


def _make_evidence_item(raw_resp: dict, itype: str, capability: str,
                        provider: dict | None = None) -> dict:
    """Normalize a provider EvidenceResponse into a Core evidence item."""
    verdict = raw_resp.get("verdict") or "insufficient_evidence"
    signal = ("supporting" if verdict == "supports"
              else ("contradictory" if verdict == "contradicts" else "uncertain"))
    conf_val = raw_resp.get("confidence", 0)
    conf = (round(conf_val * 100) if isinstance(conf_val, (int, float)) and conf_val <= 1.0
            else round(float(conf_val or 0)))

    obs = raw_resp.get("observations") or []
    facts = raw_resp.get("facts") or []
    sources = raw_resp.get("sources") or []
    if obs:
        finding = "; ".join(o.get("text", "") for o in obs[:5] if o.get("text"))
    elif facts:
        finding = "; ".join(f.get("text", "") for f in facts[:5] if f.get("text"))
    else:
        finding = (raw_resp.get("finding")
                   or f"Evidence processed for {raw_resp.get('type') or itype} ({verdict})")

    payment_info = raw_resp.get("_payment") or {}
    cost_usdc = 0.0
    if payment_info.get("amountMicro"):
        cost_usdc = payment_info["amountMicro"] / USDC_DECIMALS

    # Provider-supplied independence is preserved verbatim and never invented:
    # True/False/None all flow through. It feeds evidence classification and
    # the de-weighting logic (independent=False counts as dependent evidence).
    independent = raw_resp.get("independent")
    if independent is None:
        independent = raw_resp.get("independence")

    return {
        "id": raw_resp.get("evidence_id") or _nanoid("ev"),
        "type": raw_resp.get("type") or itype or "text",
        "source": f"{(provider or {}).get('providerName') or 'Evidence Services'} ({raw_resp.get('type') or itype})",
        "providerId": (provider or {}).get("providerId"),
        "providerName": (provider or {}).get("providerName"),
        "providerUrl": (provider or {}).get("providerUrl"),
        "serviceId": (provider or {}).get("id"),
        "timestamp": _now_iso(),
        "finding": finding,
        "confidence": min(100, max(0, conf)),
        "status": "collected",
        "cost": cost_usdc,
        "signal": signal,
        "capability": raw_resp.get("type") or capability or itype,
        "verificationStatus": "verified",
        "metadata": raw_resp,
        # Preserve structured evidence data for analyzers
        "observations": obs,
        "facts": facts,
        "sources": sources,
        "limitations": raw_resp.get("limitations") or [],
        "relationships": raw_resp.get("relationships") or [],
        "citations": raw_resp.get("citations") or [],
        "independent": independent,
    }


def _first_raw_input_file(inv: dict) -> tuple[bytes | None, str | None, str | None]:
    """Return (bytes, filename, mime) of the first raw file input, if any.

    Only stored uploads qualify — Core never fabricates a file for the provider.
    """
    for inp in inv.get("inputs") or []:
        file_path = inp.get("filePath")
        if not file_path:
            continue
        p = storage.resolve_stored_path(file_path)
        if p and p.is_file():
            try:
                return p.read_bytes(), (inp.get("fileName") or p.name), (inp.get("mimeType") or "")
            except OSError:
                continue
    return None, None, None


def _record_evidence_payment(payment_info: dict, ev_item: dict,
                             investigation_id: str, user_id: str | None) -> None:
    """Record a downstream evidence payment if one was settled."""
    if not payment_info.get("settlementRef") or not user_id:
        return
    db.save_payment({
        "id": _nanoid("pay"),
        "userId": user_id,
        "investigationId": investigation_id,
        "providerId": "evidence-services",
        "capability": ev_item["capability"],
        "amount": ev_item.get("cost") or 0.0,
        "currency": "USDC",
        "network": payment_info.get("network", config.ALGORAND_NETWORK),
        "protocol": "x402",
        "status": "settled",
        "settlementRef": payment_info["settlementRef"],
        "timestamp": _now_iso(),
    })


def _catalog_price(svc: dict | None) -> float:
    """Advertised price (USDC) for a provider service, 0 when unknown."""
    if not svc:
        return 0.0
    try:
        if svc.get("priceUsdc") is not None:
            return float(svc["priceUsdc"])
        if svc.get("priceMicro") is not None:
            return float(svc["priceMicro"]) / config.ALGORAND_USDC_DECIMALS
        if svc.get("price_usdc") is not None:
            return float(svc["price_usdc"])
        return 0.0
    except (TypeError, ValueError):
        return 0.0


def _select_evidence_type(itype: str, est_cost: float, expected_value: float,
                          budget_ctx: dict | None) -> dict:
    """Economic selection for one evidence type; rationale is always recorded.

    ponytail: heuristic value (1.0 planner-required, 0.5 assist-type); rebalance
    from real usage data if selection ever needs finer granularity.
    """
    entry = {"serviceType": itype, "expectedValue": expected_value,
             "estimatedCostUsdc": round(est_cost, 6) if est_cost else 0.0}
    if est_cost <= 0:
        return {**entry, "selected": True, "reason": "provider_in_free_or_dev_mode"}
    try:
        max_inv = float((budget_ctx or {}).get("maxPerInvestigation") or 0) or None
    except (TypeError, ValueError):
        max_inv = None
    if max_inv and est_cost > max_inv:
        return {**entry, "selected": False,
                "reason": "cost_exceeds_per_investigation_budget"}
    if expected_value < 1.0:
        return {**entry, "selected": False,
                "reason": "expected_value_below_cost_threshold"}
    return {**entry, "selected": True, "reason": "value_justifies_cost"}


def _stopping_decision(evidence: list[dict], inv: dict | None = None) -> dict:
    """Adaptive stopping: stop buying further evidence once the question is
    already answered. Stops on a high-confidence contradiction (a disproving
    finding) or on strong, consistent supporting evidence.

    ponytail: 60% / 65% thresholds are heuristics; tune from real flows.
    """
    effective = [e for e in evidence if e.get("independent") is not False]
    if len(effective) < 2:
        return {"stop": False}
    contradicting = [e for e in effective if e.get("signal") == "contradictory"]
    supporting = [e for e in effective if e.get("signal") == "supporting"]
    if (inv or {}).get("capability") == "claim-investigation":
        provider_ids = {
            e.get("providerId") for e in effective
            if e.get("providerId") and e.get("independent") is True
        }
        if len(provider_ids) < 2:
            return {"stop": False, "reason": "independent_provider_coverage_incomplete"}
    if contradicting and max((e.get("confidence") or 0) for e in contradicting) >= 60:
        return {"stop": True, "reason": "high_confidence_contradicting_evidence"}
    if len(supporting) >= 2:
        avg = sum((e.get("confidence") or 0) for e in supporting) / len(supporting)
        if avg >= 65:
            return {"stop": True, "reason": "sufficient_supporting_evidence"}
    return {"stop": False}


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


async def _run_synthesis_services(inv: dict, collected: list[dict], question: str,
                                  budget_ctx: dict | None,
                                  user_id: str | None,
                                  service_types: set | None = None) -> None:
    """Selectively run the analysis-type evidence services this investigation needs.

    Assessment/authenticity run when there is evidence to weigh; contradiction,
    duplicate and provenance analyses need at least two evidence items; timeline
    runs when timestamps exist. Every service is gated on the provider's own
    /api/services advertisement (service_types); None means unknown → run as before.
    """
    investigation_id = inv.get("id") or ""
    n = len(collected)

    def offered(name: str) -> bool:
        return service_types is None or name in service_types

    async def _pay_record(resp, cap_name):
        pay = resp.get("_payment") or {}
        if pay.get("settlementRef") and user_id:
            db.save_payment({
                "id": _nanoid("pay"), "userId": user_id,
                "investigationId": investigation_id,
                "providerId": "evidence-services",
                "capability": cap_name,
                "amount": (pay.get("amountMicro") or 0) / USDC_DECIMALS,
                "currency": "USDC",
                "network": pay.get("network", config.ALGORAND_NETWORK),
                "protocol": "x402", "status": "settled",
                "settlementRef": pay["settlementRef"],
                "timestamp": _now_iso(),
            })
            if budget_ctx and user_id:
                await _update_budget_spends(budget_ctx, user_id, investigation_id)

    if offered("assess"):
        try:
            resp = await evidence_client.call_assess(collected, claim=question,
                                                     budget_ctx=budget_ctx)
            if resp:
                inv["assessment"] = resp
                await _pay_record(resp, "assess")
        except Exception:
            pass

    if n >= 2:
        if offered("contradictions"):
            try:
                resp = await evidence_client.call_contradictions(
                    collected, claim=question, budget_ctx=budget_ctx)
                if resp:
                    inv["contradictions"] = resp.get("contradictions") or resp
                    await _pay_record(resp, "contradictions")
            except Exception:
                pass
        if offered("duplicates"):
            try:
                resp = await evidence_client.call_duplicates(
                    collected, claim=question, budget_ctx=budget_ctx)
                if resp:
                    inv["duplicates"] = resp
                    await _pay_record(resp, "duplicates")
            except Exception:
                pass
        if offered("cross-modal"):
            try:
                cm_resp = await evidence_client.call_cross_modal(
                    collected, claim=question, budget_ctx=budget_ctx)
                if cm_resp:
                    inv["crossModalAnalysis"] = cm_resp
                    await _pay_record(cm_resp, "cross-modal")
            except Exception:
                pass
        if offered("provenance"):
            try:
                prov_resp = await evidence_client.call_provenance(
                    collected, budget_ctx=budget_ctx)
                if prov_resp:
                    if prov_resp.get("graph"):
                        inv["evidenceGraph"] = prov_resp.get("graph")
                    inv["provenance"] = prov_resp
            except Exception:
                pass

    has_timestamps = any(e.get("metadata", {}).get("timestamps") for e in collected)
    if has_timestamps and offered("timeline"):
        try:
            tl_resp = await evidence_client.call_timeline(
                collected, claim=question, budget_ctx=budget_ctx)
            if tl_resp and tl_resp.get("events"):
                inv["timeline"] = tl_resp.get("events")
        except Exception:
            pass

    # Authenticity validates a raw evidence artifact (multipart), never refs.
    if offered("authenticity"):
        raw_file, raw_name, raw_mime = _first_raw_input_file(inv)
        try:
            auth_resp = await evidence_client.call_authenticity(
                collected, claim=question, budget_ctx=budget_ctx,
                file_bytes=raw_file, filename=raw_name, mime=raw_mime)
            if auth_resp:
                inv["authenticity"] = auth_resp
                await _pay_record(auth_resp, "authenticity")
        except Exception:
            pass

    if offered("gaps"):
        try:
            gaps_resp = await evidence_client.call_gaps(
                collected, claim=question, budget_ctx=budget_ctx)
            if gaps_resp:
                inv["gaps"] = gaps_resp
                await _pay_record(gaps_resp, "gaps")
        except Exception:
            pass


async def acquire_from_evidence_services(inv: dict, user_id: str | None = None) -> list[dict]:
    """Call the deployed Evidence Services over HTTP, selectively.

    Core (the client) discovers what the provider offers via /api/services,
    decides which services this investigation actually requires (from the
    planner's evidenceRequirements + the input types), pays downstream via the
    server wallet when the provider returns 402, retries with proof, and
    preserves the full returned evidence. It never blindly calls every endpoint.

    Flow:
      User -> investigation -> discover /api/services -> decide needed services
      -> call endpoint -> 402 -> (budget check) -> Inquvia pays -> proof -> retry
      -> EvidenceResponse -> evidence preserved -> recorded spend/tx
    """
    if not evidence_client.is_configured():
        return []

    question = inv.get("question") or ""
    inputs = inv.get("inputs") or []
    capability = inv.get("capability") or ""
    investigation_id = inv.get("id") or ""
    collected = []

    # Discover what the provider offers (id, type, price, resourceUrl).
    catalog = await evidence_client.discover_remote_services()
    catalog_by_type = {}
    for service in catalog:
        service_type = service.get("type")
        if not service_type:
            continue
        current = catalog_by_type.get(service_type)
        if current is None or _catalog_price(service) < _catalog_price(current):
            catalog_by_type[service_type] = service

    # Build budget context for downstream payment enforcement.
    budget_ctx = None
    if user_id:
        budget_ctx = await _update_budget_spends(
            _build_budget_context(user_id, investigation_id),
            user_id, investigation_id,
        )

    # Decide required input-type services from the planner's requirements +
    # the actual input types present. This avoids calling every endpoint.
    required_types = _required_input_types(inv)
    input_by_type = {}
    for inp in inputs:
        t = inp.get("type")
        if not t and (inp.get("content") or "").startswith(("http://", "https://")):
            t = "url"
        if t:
            input_by_type.setdefault(t, []).append(inp)

    plan_types = {r.get("capability") or r.get("type")
                  for r in (inv.get("evidenceRequirements") or [])}
    candidates = [t for t in sorted(required_types) if input_by_type.get(t) or not input_by_type]
    inv.setdefault("selectionRationale", [])

    for idx, itype in enumerate(candidates):
        est_cost = _catalog_price(catalog_by_type.get(itype))
        expected_value = 1.0 if itype in plan_types else 0.5
        rationale = _select_evidence_type(itype, est_cost, expected_value, budget_ctx)
        inv["selectionRationale"].append(rationale)
        if not rationale["selected"]:
            continue

        for inp in input_by_type.get(itype, [{}]):
            if itype not in catalog_by_type:
                raw_resp = None
            else:
                provider = catalog_by_type.get(itype)
                raw_resp = await _call_input_evidence(
                    itype, inp, question, budget_ctx,
                    provider_url=(provider or {}).get("providerUrl"),
                )

            if not raw_resp:
                continue

            ev_item = _make_evidence_item(raw_resp, itype, capability, provider)
            collected.append(ev_item)

            payment_info = raw_resp.get("_payment") or {}
            _record_evidence_payment(payment_info, ev_item, investigation_id, user_id)
            if budget_ctx and user_id and payment_info.get("settlementRef"):
                await _update_budget_spends(budget_ctx, user_id, investigation_id)

        # Adaptive stopping: stop buying when evidence already answers the question.
        if collected:
            decision = _stopping_decision(collected, inv)
            if decision.get("stop"):
                skipped = candidates[idx + 1:]
                inv["selectionRationale"].append({
                    "phase": "adaptive_stopping",
                    "stopped": True,
                    "reason": decision["reason"],
                    "evidenceTypesSkipped": skipped,
                })
                break

    # Selectively run synthesis/analysis services that this investigation needs,
    # gated on the provider's own advertised catalog.
    if collected:
        await _run_synthesis_services(inv, collected, question, budget_ctx, user_id,
                                      service_types={s["type"] for s in catalog} or None)

    return collected


async def discover_and_acquire(investigation_id: str, user_id: str) -> dict:
    inv2 = db.get_investigation(investigation_id)
    if not inv2:
        raise ValueError("Investigation not found")

    _set_stage(inv2, "discovering", "active")
    db.save_investigation(inv2)

    # Evidence is acquired ONLY through the deployed Evidence Services with the
    # server wallet paying downstream (Tx #1 user -> Inquvia, Tx #2 Inquvia ->
    # provider). There is no user-pay fallback: when the M2M path yields nothing
    # the investigation ends honestly as evidence_unavailable and the human is
    # never asked to pay an evidence provider directly.
    if evidence_client.is_configured():
        _emit(inv2, "evidence_requested", "Requesting evidence from deployed Evidence Services")
        _set_stage(inv2, "evidence_requested", "active")
        ev_items = await acquire_from_evidence_services(inv2, user_id=user_id)
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
                    "amountMicro": round((ev.get("cost") or 0) * USDC_DECIMALS),
                })
            _set_stage(inv2, "discovering", "completed")
            _set_stage(inv2, "evidence_requested", "completed")
            _set_stage(inv2, "evidence_received", "completed")
            _emit(inv2, "evidence_received", f"Received {len(ev_items)} evidence package(s) from Evidence Services")
            db.save_investigation(inv2)
            return await await_finalize_investigation(investigation_id)

    inv2["blockReason"] = (
        "No evidence was acquired through the M2M Evidence Services path"
        + ("" if evidence_client.is_configured() else " (no Evidence Services configured)")
    )
    _emit(inv2, "evidence_unavailable",
          "No M2M evidence acquired; the user is not asked to pay an evidence provider")
    _set_stage(inv2, "discovering", "completed")
    _set_stage(inv2, "evidence_requested", "completed")
    inv2["updatedAt"] = _now_iso()
    db.save_investigation(inv2)
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