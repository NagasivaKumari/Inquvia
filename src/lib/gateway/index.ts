import algosdk from "algosdk";
import { nanoid } from "nanoid";
import type {
  ActivityEvent,
  BudgetDecision,
  DiscoveredService,
  EvidenceAcquisition,
  EvidenceItem,
  Investigation,
  PaymentState,
} from "../types";
import { ALGORAND_CONFIG } from "../config";
import {
  getInvestigation,
  saveInvestigation,
  savePayment,
  getUserById,
  getPaymentsForInvestigation,
  listPayments,
} from "../db";
import { discoverServices, selectServiceForRequirement } from "./discovery";
import { buildBudgetContext, enforceBudget } from "./budget";
import { acquireEvidenceServerSide } from "../x402/serverClient";
import { createServerSigner } from "../wallet/serverSigner";

/**
 * Evidence Acquisition Gateway — the SINGLE path through which Inquvia
 * acquires external evidence. The Investigation Engine must never call an
 * external evidence service directly; it goes through here.
 *
 * Server side is authoritative for: discovery, budget enforcement, settlement
 * verification, evidence normalization, state transitions and activity events.
 */

function algod(): algosdk.Algodv2 {
  return new algosdk.Algodv2(
    ALGORAND_CONFIG.algodToken,
    ALGORAND_CONFIG.algodServer,
    ALGORAND_CONFIG.algodPort
  );
}

/* ── Activity events ── */

function emitActivity(
  inv: Investigation,
  kind: ActivityEvent["kind"],
  label: string,
  detail?: string
): void {
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

/* ── Spending context ── */

async function spentMicroForInvestigation(investigationId: string): Promise<number> {
  return (await getPaymentsForInvestigation(investigationId))
    .filter((p) => p.status === "settled")
    .reduce((s, p) => s + Math.round(p.amount * 1e6), 0);
}

async function totalSpentMicro(userId: string): Promise<number> {
  return (await listPayments(10000))
    .filter((p) => p.status === "settled")
    .reduce((s, p) => s + Math.round(p.amount * 1e6), 0);
}

/* ── Discovery + planning (server half) ── */

export interface AcquisitionPlan {
  okay: boolean;
  acquisitions: EvidenceAcquisition[];
  blockedReason?: string;
}

export async function planAcquisitions(
  investigationId: string,
  userId: string
): Promise<AcquisitionPlan> {
  const inv = await getInvestigation(investigationId);
  if (!inv) {
    return { okay: false, acquisitions: [], blockedReason: "Investigation not found" };
  }
  const user = userId ? await getUserById(userId) : null;
  const requirements = inv.evidenceRequirements ?? [];

  if (requirements.length === 0) {
    return { okay: true, acquisitions: [] };
  }

  // Real discovery — never fabricates services.
  const discovery = await discoverServices(requirements);
  inv.discovery = discovery;
  emitActivity(
    inv,
    "service_discovered",
    discovery.services.length > 0
      ? `Discovered ${discovery.services.length} evidence service(s)`
      : "No compatible evidence service discovered",
    discovery.source
  );

  const acquisitions: EvidenceAcquisition[] = [];
  for (const requirement of requirements) {
    const service = selectServiceForRequirement(requirement, discovery.services);

    if (!service) {
      acquisitions.push({
        id: `acq_${nanoid(8)}`,
        requirementId: requirement.id,
        investigationId,
        capability: requirement.capability,
        amountMicro: 0,
        assetId: ALGORAND_CONFIG.usdcAsa,
        network: ALGORAND_CONFIG.network,
        paymentState: "provider_unavailable",
        blockReason: "No compatible evidence service discovered",
        updatedAt: new Date().toISOString(),
      });
      emitActivity(
        inv,
        "blocked",
        `No compatible evidence service for ${requirement.capability}`,
        requirement.capability
      );
      continue;
    }

    // Backend budget enforcement (authoritative).
    const budget: BudgetDecision = enforceBudget(service.priceMicro, {
      ...buildBudgetContext({
        prefs: user?.paymentPrefs ?? {
          maxPerEvidenceCheck: 0.01,
          maxPerInvestigation: 0.5,
          sessionBudget: 5,
          totalBudget: 50,
        },
        investigationSpent: await spentMicroForInvestigation(investigationId),
        sessionSpent: await totalSpentMicro(userId),
        totalSpent: await totalSpentMicro(userId),
      }),
      investigationSpent: await spentMicroForInvestigation(investigationId),
      sessionSpent: await totalSpentMicro(userId),
      totalSpent: await totalSpentMicro(userId),
    });

    const acquisition: EvidenceAcquisition = {
      id: `acq_${nanoid(8)}`,
      requirementId: requirement.id,
      investigationId,
      serviceId: service.id,
      serviceName: service.name,
      capability: requirement.capability,
      amountMicro: service.priceMicro,
      assetId: service.assetId,
      network: ALGORAND_CONFIG.network,
      paymentState: budget.allowed ? "payment_required" : "payment_failed",
      blockReason: budget.allowed ? undefined : budgetBlockReason(budget),
      updatedAt: new Date().toISOString(),
    };
    acquisitions.push(acquisition);

    if (budget.allowed) {
      emitActivity(
        inv,
        "payment_required",
        `${service.name}: ${(service.priceMicro / 1e6).toFixed(4)} USDC required`,
        requirement.capability
      );
    } else {
      emitActivity(
        inv,
        "blocked",
        `Evidence check blocked by budget limit`,
        budget.reason
      );
    }
  }

  inv.acquisitions = acquisitions;
  await saveInvestigation(inv);
  return { okay: true, acquisitions };
}

function budgetBlockReason(d: BudgetDecision): string {
  switch (d.reason) {
    case "per_evidence":
      return `Cost exceeds per-evidence-check limit`;
    case "per_investigation":
      return `Exceeds per-investigation budget`;
    case "session_budget":
      return `Exceeds session budget`;
    case "total_budget":
      return `Exceeds total budget`;
    default:
      return "Blocked by spending limit";
  }
}

/* ── Settlement verification (server, on-chain) ── */

export interface SettlementProof {
  confirmed: boolean;
  txId?: string;
  sender?: string;
  amount?: number;
  confirmedRound?: number;
}

export async function verifySettlementOnChain(txId: string): Promise<SettlementProof> {
  const client = algod();
  try {
    const pending = await client.pendingTransactionInformation(txId).do();
    if (pending && typeof pending.confirmedRound === "number" && pending.confirmedRound > 0) {
      return {
        confirmed: true,
        txId,
        confirmedRound: pending.confirmedRound,
      };
    }
    return { confirmed: false, txId };
  } catch {
    return { confirmed: false, txId };
  }
}

/* ── Evidence normalization ── */

export function normalizeEvidence(
  acquisition: EvidenceAcquisition,
  raw: unknown
): EvidenceItem {
  const data = (raw ?? {}) as Record<string, unknown>;
  const meta = (data.metadata ?? data.evidence ?? {}) as Record<string, unknown>;
  const text =
    typeof data.finding === "string"
      ? data.finding
      : typeof meta === "object" && meta !== null && "summary" in meta && typeof (meta as any).summary === "string"
        ? (meta as any).summary
        : "";

  return {
    id: `ev_${nanoid(8)}`,
    type: acquisition.capability.includes("image")
      ? "image"
      : acquisition.capability.includes("video")
        ? "video"
        : acquisition.capability.includes("document")
          ? "document"
          : acquisition.capability.includes("url") || acquisition.capability.includes("domain")
            ? "url"
            : "text",
    source: acquisition.serviceName ?? acquisition.serviceId ?? "External evidence service",
    timestamp: new Date().toISOString(),
    finding: text || `Evidence acquired from ${acquisition.serviceName ?? "external service"}`,
    confidence:
      typeof meta === "object" && meta !== null && "confidence" in meta
        ? clampConfidence(Number((meta as any).confidence))
        : 0,
    status: "collected",
    cost: acquisition.amountMicro / 1e6,
    signal: evidenceSignal(meta),
    capability: acquisition.capability,
    acquisitionId: acquisition.id,
    paymentId: acquisition.txId,
    verificationStatus: "unverified",
    metadata: meta,
  };
}

function clampConfidence(v: number): number {
  if (Number.isNaN(v)) return 0;
  return Math.min(100, Math.max(0, Math.round(v)));
}

function evidenceSignal(meta: Record<string, unknown>): EvidenceItem["signal"] {
  if (meta === null) return "uncertain";
  const raw = (meta as any).signal;
  if (raw === "supporting" || raw === "contradictory") return raw;
  return "uncertain";
}

/* ── Recording a completed acquisition (after client signing + settlement) ── */

export interface RecordAcquisitionPayload {
  acquisitionId: string;
  txId: string;
  evidence?: unknown;
}

export interface RecordAcquisitionResult {
  ok: boolean;
  error?: string;
  investigation?: Investigation;
}

export async function recordAcquisition(
  investigationId: string,
  userId: string,
  payload: RecordAcquisitionPayload
): Promise<RecordAcquisitionResult> {
  const inv = await getInvestigation(investigationId);
  if (!inv) return { ok: false, error: "Investigation not found" };
  if (inv.userId && inv.userId !== userId) {
    return { ok: false, error: "Forbidden" };
  }
  const acq = (inv.acquisitions ?? []).find((a) => a.id === payload.acquisitionId);
  if (!acq) return { ok: false, error: "Acquisition not found" };

  // Idempotent: already resolved/received -> report success.
  if (acq.paymentState === "evidence_received" || acq.paymentState === "settled") {
    return { ok: true, investigation: inv };
  }
  // Never accept evidence from a blocked acquisition.
  if (
    acq.paymentState === "provider_unavailable" ||
    acq.paymentState === "payment_failed" ||
    acq.paymentState === "settlement_failed"
  ) {
    return { ok: false, error: `Acquisition not in a payable state (${acq.paymentState})` };
  }

  // Client reported a settlement for a payment_required acquisition -> the
  // client has signed + settled x402 on facilitator. Mark as submitted.
  if (!payload.txId) {
    return { ok: false, error: "Missing payment transaction" };
  }

  acq.paymentState = "payment_submitted";
  acq.txId = payload.txId;
  acq.updatedAt = new Date().toISOString();
  emitActivity(
    inv,
    "x402_payment_submitted",
    "Payment submitted for settlement verification",
    acq.txId
  );
  await saveInvestigation(inv);

  return finalizeAcquisition(inv, acq, payload.txId, payload.evidence);
}

/**
 * Shared post-payment handler: verify settlement on-chain, persist the real
 * payment, and record the acquired evidence. Used by both the client-reported
 * path (recordAcquisition) and the server-wallet path (acquireDownstream).
 */
async function finalizeAcquisition(
  inv: Investigation,
  acq: EvidenceAcquisition,
  txId: string,
  rawEvidence: unknown
): Promise<RecordAcquisitionResult> {
  // Verify settlement on-chain BEFORE recording evidence.
  const proof = await verifySettlementOnChain(txId);
  if (!proof.confirmed) {
    acq.paymentState = "settlement_failed";
    acq.blockReason = "Settlement could not be verified on-chain";
    emitActivity(
      inv,
      "failed",
      "Settlement could not be verified on-chain",
      acq.txId
    );
    await saveInvestigation(inv);
    return { ok: false, error: "Settlement not confirmed on Algorand" };
  }

  acq.paymentState = "settled";
  acq.txId = proof.txId ?? txId;
  acq.updatedAt = new Date().toISOString();

  // Persist a real payment record.
  await savePayment({
    id: `pay_${nanoid(8)}`,
    investigationId: inv.id,
    providerId: acq.serviceId ?? acq.serviceName ?? "unknown",
    capability: acq.capability,
    amount: acq.amountMicro / 1e6,
    currency: "USDC",
    network: acq.network,
    protocol: "x402",
    status: "settled",
    settlementRef: acq.txId,
    timestamp: new Date().toISOString(),
  });
  emitActivity(
    inv,
    "settlement_confirmed",
    `Settlement confirmed on Algorand (${acq.txId?.slice(0, 12)}…)`,
    acq.txId
  );

  // Record the acquired evidence.
  const evidence = normalizeEvidence(acq, rawEvidence ?? {});
  evidence.paymentId = acq.txId;
  evidence.acquisitionId = acq.id;
  acq.evidence = evidence;
  inv.evidence = inv.evidence ?? [];
  if (!inv.evidence.some((e) => e.id === evidence.id)) {
    inv.evidence.push(evidence);
  }
  acq.paymentState = "evidence_received";
  emitActivity(
    inv,
    "evidence_received",
    `Evidence received from ${acq.serviceName ?? "external service"}`,
    acq.capability
  );

  await saveInvestigation(inv);
  return { ok: true, investigation: inv };
}

/**
 * Orchestrator downstream acquisition: Inquvia's backend pays an evidence
 * service from its own wallet (via x402) and records the evidence. Env-gated
 * on SERVER_WALLET_MNEMONIC + a discovered service with a resource URL. When
 * not configured or no service is available, the acquisition is marked
 * provider_unavailable rather than fabricating anything.
 */
export async function acquireDownstream(
  investigationId: string,
  userId: string
): Promise<RecordAcquisitionResult> {
  const inv = await getInvestigation(investigationId);
  if (!inv) return { ok: false, error: "Investigation not found" };
  if (inv.userId && inv.userId !== userId) {
    return { ok: false, error: "Forbidden" };
  }
  if (!createServerSigner()) {
    return { ok: false, error: "Server wallet not configured" };
  }

  const pending = (inv.acquisitions ?? []).filter(
    (a) => a.paymentState === "payment_required"
  );
  if (pending.length === 0) {
    return { ok: true, investigation: inv };
  }

  for (const acq of pending) {
    const service = (inv.discovery?.services ?? []).find(
      (s) => s.id === acq.serviceId
    );
    const endpoint = service?.resourceUrl;
    if (!endpoint) {
      acq.paymentState = "provider_unavailable";
      acq.blockReason = "No payable service endpoint for this acquisition";
      continue;
    }
    acq.paymentState = "awaiting_wallet";
    acq.updatedAt = new Date().toISOString();
    await saveInvestigation(inv);

    try {
      const { txId, evidence } = await acquireEvidenceServerSide({
        endpoint,
        question: inv.question,
        capability: acq.capability,
      });
      acq.paymentState = "payment_submitted";
      acq.txId = txId;
      acq.updatedAt = new Date().toISOString();
      await saveInvestigation(inv);
      await finalizeAcquisition(inv, acq, txId, evidence);
    } catch (err) {
      acq.paymentState = "payment_failed";
      acq.blockReason =
        err instanceof Error ? err.message : "Downstream payment failed";
      acq.updatedAt = new Date().toISOString();
      await saveInvestigation(inv);
    }
  }

  const saved = await getInvestigation(investigationId);
  return { ok: true, investigation: saved ?? undefined };
}

/** Create the initial Investigation record with the new state machine. */
export function createInvestigationRecord(input: {
  id: string;
  userId?: string;
  title: string;
  question: string;
  inputs: Investigation["inputs"];
  inputType: Investigation["inputType"];
  status: Investigation["status"];
  capability?: string;
  capabilityPriceUsdc?: number;
  idempotencyKey?: string;
}): Investigation {
  const now = new Date().toISOString();
  return {
    id: input.id,
    userId: input.userId,
    title: input.title,
    capability: input.capability,
    capabilityPriceUsdc: input.capabilityPriceUsdc,
    idempotencyKey: input.idempotencyKey,
    question: input.question,
    inputs: input.inputs,
    inputType: input.inputType,
    investigationPlan: [],
    selectedCapabilities: [],
    evidence: [],
    contradictions: [],
    conclusion: "inconclusive",
    conclusionText: "",
    confidence: 0,
    risk: "unknown",
    limitations: [],
    economicSummary: {
      totalSpend: 0,
      checksPurchased: 0,
      providerCategories: [],
      settlementStatus: "Pending",
    },
    status: input.status,
    stages: [],
    createdAt: now,
    updatedAt: now,
    findings: [],
    supportingEvidenceIds: [],
    contradictoryEvidenceIds: [],
    evidenceRequirements: [],
    acquisitions: [],
    activity: [],
    evidenceGraph: { nodes: [], edges: [] },
  };
}
