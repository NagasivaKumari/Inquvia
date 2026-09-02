import type { BudgetContext, BudgetDecision } from "../types";

/**
 * Server-side spending-limit enforcement for the Evidence Acquisition Gateway.
 *
 * All amounts are in micro-units (6 decimal USDC). The frontend can show
 * estimated totals, but the authoritative gate is here — the backend blocks
 * any acquisition whose cost exceeds the user's configured limits.
 */
export function enforceBudget(requestedMicro: number, ctx: BudgetContext): BudgetDecision {
  const remainingPerInvestigation =
    ctx.maxPerInvestigation * 1e6 - ctx.investigationSpent;
  const remainingSession = ctx.sessionBudget * 1e6 - ctx.sessionSpent;
  const remainingTotal = ctx.totalBudget * 1e6 - ctx.totalSpent;

  if (requestedMicro <= 0) {
    return {
      allowed: false,
      reason: "per_evidence",
      amountMicro: requestedMicro,
      limitMicro: Math.round(ctx.maxPerEvidenceCheck * 1e6),
      remainingMicro: 0,
    };
  }

  if (requestedMicro > ctx.maxPerEvidenceCheck * 1e6) {
    return {
      allowed: false,
      reason: "per_evidence",
      amountMicro: requestedMicro,
      limitMicro: Math.round(ctx.maxPerEvidenceCheck * 1e6),
      remainingMicro: 0,
    };
  }
  if (requestedMicro > remainingPerInvestigation) {
    return {
      allowed: false,
      reason: "per_investigation",
      amountMicro: requestedMicro,
      limitMicro: Math.max(0, Math.round(remainingPerInvestigation)),
      remainingMicro: Math.max(0, Math.round(remainingPerInvestigation)),
    };
  }
  if (requestedMicro > remainingSession) {
    return {
      allowed: false,
      reason: "session_budget",
      amountMicro: requestedMicro,
      limitMicro: Math.max(0, Math.round(remainingSession)),
      remainingMicro: Math.max(0, Math.round(remainingSession)),
    };
  }
  if (requestedMicro > remainingTotal) {
    return {
      allowed: false,
      reason: "total_budget",
      amountMicro: requestedMicro,
      limitMicro: Math.max(0, Math.round(remainingTotal)),
      remainingMicro: Math.max(0, Math.round(remainingTotal)),
    };
  }
  return {
    allowed: true,
    amountMicro: requestedMicro,
    limitMicro: Math.round(ctx.maxPerEvidenceCheck * 1e6),
    remainingMicro: Math.max(0, Math.round(remainingPerInvestigation)),
  };
}

/** Build a BudgetContext from a user + an investigation. */
export function buildBudgetContext(input: {
  prefs: { maxPerEvidenceCheck: number; maxPerInvestigation: number; sessionBudget: number; totalBudget: number };
  investigationSpent: number;
  sessionSpent: number;
  totalSpent: number;
}): BudgetContext {
  return {
    maxPerEvidenceCheck: input.prefs.maxPerEvidenceCheck,
    maxPerInvestigation: input.prefs.maxPerInvestigation,
    sessionBudget: input.prefs.sessionBudget,
    totalBudget: input.prefs.totalBudget,
    investigationSpent: input.investigationSpent,
    sessionSpent: input.sessionSpent,
    totalSpent: input.totalSpent,
  };
}
