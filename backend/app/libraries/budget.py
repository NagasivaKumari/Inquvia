"""Server-side spending-limit enforcement (mirrors gateway/budget.ts). All
amounts are in micro-units (6-decimal USDC)."""


def enforce_budget(requested_micro: float, ctx: dict) -> dict:
    remaining_per_investigation = ctx["maxPerInvestigation"] * 1_000_000 - ctx["investigationSpent"]
    remaining_session = ctx["sessionBudget"] * 1_000_000 - ctx["sessionSpent"]
    remaining_total = ctx["totalBudget"] * 1_000_000 - ctx["totalSpent"]

    if requested_micro <= 0:
        return {"allowed": False, "reason": "per_evidence",
                "amountMicro": requested_micro, "limitMicro": round(ctx["maxPerEvidenceCheck"] * 1_000_000),
                "remainingMicro": 0}

    if requested_micro > ctx["maxPerEvidenceCheck"] * 1_000_000:
        return {"allowed": False, "reason": "per_evidence",
                "amountMicro": requested_micro, "limitMicro": round(ctx["maxPerEvidenceCheck"] * 1_000_000),
                "remainingMicro": 0}
    if requested_micro > remaining_per_investigation:
        return {"allowed": False, "reason": "per_investigation",
                "amountMicro": requested_micro, "limitMicro": max(0, round(remaining_per_investigation)),
                "remainingMicro": max(0, round(remaining_per_investigation))}
    if requested_micro > remaining_session:
        return {"allowed": False, "reason": "session_budget",
                "amountMicro": requested_micro, "limitMicro": max(0, round(remaining_session)),
                "remainingMicro": max(0, round(remaining_session))}
    if requested_micro > remaining_total:
        return {"allowed": False, "reason": "total_budget",
                "amountMicro": requested_micro, "limitMicro": max(0, round(remaining_total)),
                "remainingMicro": max(0, round(remaining_total))}
    return {"allowed": True, "amountMicro": requested_micro,
            "limitMicro": round(ctx["maxPerEvidenceCheck"] * 1_000_000),
            "remainingMicro": max(0, round(remaining_per_investigation))}


def budget_block_reason(reason: str) -> str:
    return {
        "per_evidence": "Cost exceeds per-evidence-check limit",
        "per_investigation": "Exceeds per-investigation budget",
        "session_budget": "Exceeds session budget",
        "total_budget": "Exceeds total budget",
    }.get(reason, "Blocked by spending limit")