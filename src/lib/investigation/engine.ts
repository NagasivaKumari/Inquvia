import { nanoid } from "nanoid";
import {
  INVESTIGATION_STAGES,
  INVESTIGATION_BLOCKED_STATES,
  getPaidCapability,
} from "../config";
import {
  getInvestigation,
  saveInvestigation,
  getUserById,
} from "../db";
import type {
  ActivityEvent,
  AssessmentLabel,
  EvidenceItem,
  Investigation,
  InvestigationInput,
  InputType,
  PaymentState,
  RiskLevel,
  StageProgress,
} from "../types";
import { planEvidenceRequirements } from "./planner";
import {
  planAcquisitions,
  createInvestigationRecord,
} from "../gateway";
import { acquireDownstream } from "../gateway";
import { createServerSigner } from "../wallet/serverSigner";
import { AnalysisResult, heuristicAnalysis, buildEvidenceGraph } from "./analyze";
import { getAnalyzer, type CapabilityAnalyzer } from "./analyzers";

export interface InvestigationRequest {
  question: string;
  inputs: InvestigationInput[];
  id?: string;
  userId?: string;
}

/** Acquisition states that are finished (resolution can proceed past them). */
const RESOLVED_STATES: PaymentState[] = [
  "evidence_received",
  "settled",
  "provider_unavailable",
  "payment_failed",
  "settlement_failed",
  "wallet_rejected",
  "unsupported_network",
  "insufficient_balance",
  "evidence_request_failed",
];

function detectInputType(inputs: InvestigationInput[]): InputType {
  const types = new Set(inputs.map((i) => i.type));
  if (types.size > 1) return "mixed";
  return inputs[0]?.type ?? "text";
}

function setStage(inv: Investigation, stageId: string, status: StageProgress["status"]) {
  inv.stages = inv.stages.map((s) =>
    s.id === stageId ? { ...s, status } : s
  );
}

function initStages(): StageProgress[] {
  return INVESTIGATION_STAGES.map((s) => ({
    id: s.id,
    label: s.label,
    status: "pending" as const,
  }));
}

function emit(
  inv: Investigation,
  kind: ActivityEvent["kind"],
  label: string,
  detail?: string
) {
  inv.activity = inv.activity ?? [];
  inv.activity.push({
    id: `evt_${nanoid(8)}`,
    investigationId: inv.id,
    userId: inv.userId,
    kind,
    label,
    detail,
    createdAt: new Date().toISOString(),
  });
}

export interface CapabilityStartInput {
  id: string;
  userId?: string;
  question: string;
  inputs: InvestigationInput[];
  capability: string;
  title?: string;
  idempotencyKey?: string;
}

/**
 * Create the record for a new atomic capability investigation, recording which
 * x402 endpoint/capability was used and its price.
 */
export async function startCapabilityInvestigation(
  input: CapabilityStartInput
): Promise<Investigation> {
  const cap = getPaidCapability(input.capability);
  const inv = createInvestigationRecord({
    id: input.id,
    userId: input.userId,
    title: input.title ?? cap?.title ?? "Investigation in Progress",
    question: input.question,
    inputs: input.inputs,
    inputType: detectInputType(input.inputs),
    status: "created",
    capability: input.capability,
    capabilityPriceUsdc: cap?.priceUsdc,
    idempotencyKey: input.idempotencyKey,
  });
  inv.stages = initStages();
  emit(inv, "investigation_created", `${cap?.title ?? "Capability"} investigation started`);
  await saveInvestigation(inv);
  return (await getInvestigation(inv.id)) as Investigation;
}

/** Record the capability-specific evidence requirements and advance to discovery. */
export async function planCapability(inv: Investigation, requirements: Investigation["evidenceRequirements"]): Promise<Investigation> {
  const inv2 = (await getInvestigation(inv.id)) as Investigation;
  inv2.status = "planning";
  setStage(inv2, "planning", "active");
  await saveInvestigation(inv2);

  inv2.evidenceRequirements = requirements ?? [];
  inv2.investigationPlan = (requirements ?? []).map((r) => ({
    id: r.id,
    capability: r.capability,
    reason: r.reason,
    estimatedCost: 0,
    expectedValue: 0,
    status: "pending" as const,
  }));
  setStage(inv2, "planning", "completed");
  inv2.status = "discovering";
  inv2.updatedAt = new Date().toISOString();
  await saveInvestigation(inv2);
  return (await getInvestigation(inv2.id)) as Investigation;
}

/**
 * Advance an investigation through discovery and acquisition. When the server
 * wallet is configured, downstream evidence services are paid from Inquvia's
 * wallet and the investigation is finalized. Otherwise it enters the
 * awaiting_payment state for the client-side flow. Capability investigations
 * with nothing left to acquire are finalized immediately (the capability
 * analyzer runs on the submitted input itself).
 */
export async function discoverAndAcquire(
  investigationId: string,
  userId: string
): Promise<Investigation> {
  let inv2 = (await getInvestigation(investigationId)) as Investigation;
  if (!inv2) throw new Error("Investigation not found");

  setStage(inv2, "discovering", "active");
  await saveInvestigation(inv2);

  const plan = await planAcquisitions(investigationId, userId);
  inv2 = (await getInvestigation(investigationId)) as Investigation;
  inv2.acquisitions = plan.acquisitions;
  setStage(inv2, "discovering", "completed");

  const pending = plan.acquisitions.filter(
    (a) => a.paymentState === "payment_required"
  );

  if (pending.length > 0) {
    if (createServerSigner()) {
      // Auto-acquire downstream from Inquvia's own wallet (real x402).
      await acquireDownstream(investigationId, userId);
      await finalizeInvestigation(investigationId);
      return (await getInvestigation(investigationId)) as Investigation;
    }
    inv2.status = "awaiting_payment";
    setStage(inv2, "awaiting_payment", "active");
    inv2.updatedAt = new Date().toISOString();
    await saveInvestigation(inv2);
    return inv2;
  }

  // Nothing left to acquire: run the capability's own analysis to completion.
  await finalizeInvestigation(investigationId);
  return (await getInvestigation(investigationId)) as Investigation;
}

/**
 * Finalize a capability investigation: run the capability-specific analyzer
 * (or the caller-supplied one, or the legacy heuristic), write the assessment,
 * and complete the investigation. Only acquires/evidence that actually settled
 * count towards the result — nothing is fabricated.
 */
export async function finalizeInvestigation(
  id: string,
  analyze?: CapabilityAnalyzer
): Promise<Investigation> {
  const inv = await getInvestigation(id);
  if (!inv) throw new Error("Investigation not found");

  const acqs = inv.acquisitions ?? [];
  const unresolved = acqs.filter((a) => !RESOLVED_STATES.includes(a.paymentState));

  // Still waiting on user to authorize/acquire evidence.
  if (unresolved.length > 0) {
    return inv;
  }

  const evidence = (inv.evidence ?? []).filter((e) => e.status === "collected");
  const analyzer = analyze ?? getAnalyzer(inv.capability) ?? heuristicAnalysis;

  // Without a capability analyzer and without evidence, completing would mean
  // fabricating an assessment — refuse and report the honest state instead.
  if (evidence.length === 0 && !getAnalyzer(inv.capability)) {
    inv.status = "evidence_unavailable";
    inv.conclusion = "insufficient_evidence";
    inv.conclusionText =
      "Insufficient evidence was acquired to render an assessment. The investigation could not be completed because no paid external evidence was obtained.";
    inv.confidence = 0;
    inv.limitations = [
      "No external evidence was successfully acquired",
      inv.blockReason ?? "Evidence acquisition did not complete",
    ];
    inv.updatedAt = new Date().toISOString();
    await saveInvestigation(inv);
    return inv;
  }

  // ANALYZING
  inv.status = "analyzing";
  setStage(inv, "analyzing", "active");
  await saveInvestigation(inv);
  const analysis = await analyzer(inv, evidence);

  // CROSS-CHECKING
  inv.status = "cross_checking";
  setStage(inv, "analyzing", "completed");
  setStage(inv, "cross_checking", "active");
  inv.supportingEvidenceIds = evidence
    .filter((e) => e.signal === "supporting" || e.supportsClaim)
    .map((e) => e.id);
  inv.contradictoryEvidenceIds = evidence
    .filter((e) => e.signal === "contradictory" || e.contradictsClaim)
    .map((e) => e.id);
  emit(inv, "cross_check_completed", "Cross-check of acquired evidence completed");
  await saveInvestigation(inv);

  // FINAL ASSESSMENT
  inv.conclusion = analysis.conclusion;
  inv.conclusionText = analysis.conclusionText;
  inv.confidence = analysis.confidence;
  inv.risk = analysis.risk;
  inv.findings = analysis.findings;
  inv.limitations = analysis.limitations;
  inv.contradictions = analysis.contradictions;
  inv.sourcesUsed =
    analysis.sourcesUsed?.length
      ? analysis.sourcesUsed
      : evidence.map((e) => e.source);
  if (analysis.uncertainty) inv.uncertainty = analysis.uncertainty;
  inv.evidenceGraph = buildEvidenceGraph(inv, evidence);
  inv.economicSummary = {
    totalSpend: acqs
      .filter((a) => a.paymentState === "evidence_received" || a.paymentState === "settled")
      .reduce((s, a) => s + a.amountMicro / 1e6, 0),
    checksPurchased: acqs.filter((a) => a.evidence).length,
    providerCategories: [
      ...new Set(acqs.filter((a) => a.evidence).map((a) => a.capability)),
    ],
    settlementStatus: "Settled",
    algorandRef: acqs.find((a) => a.txId)?.txId,
  };
  inv.status = "completed";
  setStage(inv, "cross_checking", "completed");
  setStage(inv, "assessment", "completed");
  inv.currentStage = undefined;
  inv.updatedAt = new Date().toISOString();
  emit(inv, "assessment_generated", "Assessment generated for capability investigation");
  await saveInvestigation(inv);
  return inv;
}

/**
 * Legacy generic investigation path (a single generic endpoint). Kept only for
 * backward compatibility — new independent capabilities use
 * startCapabilityInvestigation + planCapability + discoverAndAcquire.
 */
export async function runInvestigation(
  request: InvestigationRequest
): Promise<Investigation> {
  const id = request.id ?? `case_${nanoid(10)}`;
  let inv = await getInvestigation(id);

  if (!inv) {
    inv = createInvestigationRecord({
      id,
      userId: request.userId,
      title: "Investigation in Progress",
      question: request.question,
      inputs: request.inputs,
      inputType: detectInputType(request.inputs),
      status: "created",
    });
    inv.stages = initStages();
    await saveInvestigation(inv);
    emit(inv, "investigation_created", "Investigation created");
  }

  if (inv.status === "created" || inv.status === "planning") {
    const requirements = planEvidenceRequirements(
      inv.question,
      inv.inputs.map((i) => i.type)
    );
    inv = await planCapability(inv, requirements);
  }

  if (inv.status === "discovering") {
    inv = await discoverAndAcquire(id, request.userId ?? "");
  }

  return (await getInvestigation(id)) as Investigation;
}

/** Legacy alias used by some callers. */
export async function getInvestigationProgress(
  id: string
): Promise<Investigation | null> {
  return getInvestigation(id);
}

export { INVESTIGATION_BLOCKED_STATES };
export type { AnalysisResult };