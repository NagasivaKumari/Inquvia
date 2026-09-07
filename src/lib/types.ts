import type { StageStatus } from "./config";

export type InputType =
  | "text"
  | "url"
  | "image"
  | "video"
  | "document"
  | "data"
  | "mixed";

// InvestigationStatus is defined in the Evidence Acquisition section below
// (single source of truth for the state machine).

export type EvidenceSignal = "supporting" | "contradictory" | "uncertain";

export type RiskLevel = "low" | "moderate" | "high" | "unknown";

export type AssessmentLabel =
  | "likely_genuine"
  | "likely_misleading"
  | "suspicious"
  | "insufficient_evidence"
  | "inconclusive";

export interface User {
  id: string;
  name: string;
  email: string;
  passwordHash: string;
  createdAt: string;
  updatedAt: string;
  walletAddress?: string;
  walletNetwork?: string;
  paymentPrefs: PaymentPrefs;
}

export interface PaymentPrefs {
  maxPerEvidenceCheck: number;
  maxPerInvestigation: number;
  sessionBudget: number;
  totalBudget: number;
}

export interface Session {
  id: string;
  userId: string;
  createdAt: string;
  expiresAt: string;
}

export interface WalletProviderInfo {
  id: string;
  name: string;
  icon: string;
  url: string;
}

export type AuthState =
  | "logged_out"
  | "signing_up"
  | "logged_in"
  | "wallet_disconnected"
  | "wallet_connected"
  | "payment_pending"
  | "payment_approved"
  | "payment_rejected"
  | "payment_failed"
  | "session_expired";

export const DEFAULT_PAYMENT_PREFS: PaymentPrefs = {
  maxPerEvidenceCheck: 0.01,
  maxPerInvestigation: 0.50,
  sessionBudget: 5.00,
  totalBudget: 50.00,
};

export interface InvestigationInput {
  type: InputType;
  content: string;
  fileName?: string;
  mimeType?: string;
  filePath?: string;
}

export interface Provider {
  id: string;
  name: string;
  capability: string;
  price: number;
  endpoint: string;
  network: string;
  reputation: number;
  latency: number;
  supportedInput: InputType[];
  description?: string;
}

export interface CapabilityNeed {
  id: string;
  capability: string;
  reason: string;
  estimatedCost: number;
  expectedValue: number;
  status: "pending" | "selected" | "purchased" | "failed" | "skipped";
  providerId?: string;
}

export interface ProviderScore {
  providerId: string;
  cost: number;
  expectedConfidenceGain: number;
  relevance: number;
  reliability: number;
  score: number;
  selected: boolean;
  reason?: string;
}

export interface EvidenceItem {
  id: string;
  type: string;
  source: string;
  timestamp: string;
  finding: string;
  confidence: number;
  status: "pending" | "collected" | "failed";
  cost: number;
  signal: EvidenceSignal;
  capability?: string;
  providerId?: string;
  /** Linking to the real acquisition that produced this evidence. */
  acquisitionId?: string;
  paymentId?: string;
  supportsClaim?: boolean;
  contradictsClaim?: boolean;
  verificationStatus?: "verified" | "unverified";
  /** Type-specific metadata. */
  metadata?: Record<string, unknown>;
}

export interface PaymentRecord {
  id: string;
  userId?: string;
  investigationId: string;
  providerId: string;
  capability: string;
  amount: number;
  currency: string;
  network: string;
  protocol: string;
  status: "pending" | "settled" | "failed";
  settlementRef?: string;
  timestamp: string;
}

export interface EconomicSummary {
  totalSpend: number;
  checksPurchased: number;
  providerCategories: string[];
  settlementStatus: string;
  algorandRef?: string;
}

export interface StageProgress {
  id: string;
  label: string;
  status: StageStatus;
}

export interface Investigation {
  id: string;
  userId?: string;
  title: string;
  /** The atomic paid capability this investigation ran under (e.g. "image-investigation"). */
  capability?: string;
  /** Price paid for the atomic capability, in whole USDC (merchant fee). */
  capabilityPriceUsdc?: number;
  /** Idempotency key supplied by the client, to avoid duplicate charges. */
  idempotencyKey?: string;
  /** Sources actually used by the investigation (evidence services, inspections, AI). */
  sourcesUsed?: string[];
  /** Free-form uncertainty note produced by the analysis. */
  uncertainty?: string;
  question: string;
  inputs: InvestigationInput[];
  inputType: InputType;
  investigationPlan: CapabilityNeed[];
  selectedCapabilities: ProviderScore[];
  evidence: EvidenceItem[];
  contradictions: string[];
  conclusion: AssessmentLabel;
  conclusionText: string;
  confidence: number;
  risk: RiskLevel;
  limitations: string[];
  economicSummary: EconomicSummary;
  status: InvestigationStatus;
  stages: StageProgress[];
  currentStage?: string;
  createdAt: string;
  updatedAt: string;
  findings: string[];
  supportingEvidenceIds: string[];
  contradictoryEvidenceIds: string[];
  /** Evidence requirements produced by the Evidence Planner. */
  evidenceRequirements?: EvidenceRequirement[];
  /** Real discovered external evidence services. */
  discovery?: DiscoveryResult;
  /** Per-requirement acquisition state (real payments). */
  acquisitions?: EvidenceAcquisition[];
  /** Real backend activity events. */
  activity?: ActivityEvent[];
  /** Evidence graph built from real acquired evidence. */
  evidenceGraph?: EvidenceGraph;
  /** Human reason a blocked/unavailable investigation could not complete. */
  blockReason?: string;
}

export interface DashboardStats {
  totalInvestigations: number;
  investigationsThisWeek: number;
  evidenceChecksPurchased: number;
  totalSpend: number;
  averageConfidence: number;
  casesByType: Record<InputType, number>;
  recentInvestigations: Investigation[];
}

export interface DiscoverProvidersRequest {
  capabilities: string[];
  inputTypes: InputType[];
}

export interface InvestigateRequest {
  question: string;
  text?: string;
  url?: string;
  inputs?: InvestigationInput[];
}

export const ASSESSMENT_LABELS: Record<AssessmentLabel, string> = {
  likely_genuine: "Likely Genuine",
  likely_misleading: "Likely Misleading",
  suspicious: "Suspicious",
  insufficient_evidence: "Insufficient Evidence",
  inconclusive: "Inconclusive",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  unknown: "Unknown",
};

export const SIGNAL_LABELS: Record<EvidenceSignal, string> = {
  supporting: "Supporting",
  contradictory: "Contradictory",
  uncertain: "Uncertain",
};

/* ─────────────────────────────────────────────────────────────
 * Real evidence-acquisition architecture (Evidence Acquisition Gateway)
 * ───────────────────────────────────────────────────────────── */

/** The kind of evidence a service provides. */
export type EvidenceType =
  | "text"
  | "image"
  | "video"
  | "document"
  | "url"
  | "data";

/** A concrete evidence need identified by the Evidence Planner. */
export interface EvidenceRequirement {
  id: string;
  type: EvidenceType;
  capability: string; // e.g. "image_provenance", "source_verify", "claim_support"
  reason: string;
}

/**
 * A real, discovered external evidence service. This is populated by
 * Service Discovery and is NEVER invented. When no compatible service is
 * discovered, discovery returns an empty list.
 */
export interface DiscoveredService {
  id: string;
  name: string;
  /** Capabilities/evidence types the service provides. */
  capabilities: string[];
  /** Evidence types the service supports. */
  evidenceTypes: EvidenceType[];
  /** Public HTTPS endpoint of the x402-protected evidence service. */
  resourceUrl: string;
  /** CAIP-2 network id (e.g. algorand:mainnet). */
  network: string;
  /** Price in micro-units of the payment asset (USDC micro / 1e6). */
  priceMicro: number;
  /** Payment asset ASA id (USDC on mainnet = 31566704). */
  assetId: string;
  description: string;
  /** Where this service entry came from (real discovery source only). */
  discoveredAt: string;
}

/** Outcome of Service Discovery for a requirement. */
export interface DiscoveryResult {
  requirements: EvidenceRequirement[];
  services: DiscoveredService[];
  /** "bazaar" | "configured" | "none" - never "mock". */
  source: "bazaar" | "configured" | "none";
  discoveredAt: string;
}

/** Real x402 payment / settlement state transitions. */
export type PaymentState =
  | "payment_required"
  | "awaiting_wallet"
  | "wallet_authorized"
  | "payment_submitted"
  | "settling"
  | "settled"
  | "evidence_requested"
  | "evidence_received"
  | "wallet_rejected"
  | "insufficient_balance"
  | "unsupported_network"
  | "payment_failed"
  | "settlement_failed"
  | "provider_unavailable"
  | "evidence_request_failed";

/**
 * A single evidence acquisition: a requirement matched to a real service,
 * paid via real x402, settled on-chain, then evidence retrieved.
 */
export interface EvidenceAcquisition {
  id: string;
  requirementId: string;
  investigationId: string;
  serviceId?: string;
  serviceName?: string;
  capability: string;
  amountMicro: number;
  assetId: string;
  network: string;
  /** Provider's x402 resource endpoint the user pays + fetches evidence from. */
  resourceUrl?: string;
  /** Provider's recipient address the user's payment must go to (from the
   * provider's probed 402), verified on-chain by the server. */
  payTo?: string;
  /** Sender of the verified settlement, read off-chain by the server. */
  payer?: string;
  paymentState: PaymentState;
  /** Server-verified Algorand transaction id of the settled payment. */
  txId?: string;
  /** Evidence once actually acquired (only after real retrieval). */
  evidence?: EvidenceItem;
  /** Human reason for a blocked/failed acquisition, if any. */
  blockReason?: string;
  updatedAt: string;
}

/** Live investigation states (the Investigation Status Machine). */
export type InvestigationStatus =
  | "created"
  | "planning"
  | "discovering"
  | "awaiting_payment"
  | "payment_pending"
  | "evidence_requested"
  | "evidence_received"
  | "analyzing"
  | "cross_checking"
  | "completed"
  | "payment_failed"
  | "settlement_failed"
  | "evidence_unavailable"
  | "blocked"
  | "failed";

/** A real activity event derived from actual backend state transitions. */
export interface ActivityEvent {
  id: string;
  investigationId: string;
  userId?: string;
  kind:
    | "investigation_created"
    | "evidence_requirement_identified"
    | "service_discovered"
    | "payment_required"
    | "wallet_authorized"
    | "x402_payment_submitted"
    | "settlement_confirmed"
    | "evidence_received"
    | "cross_check_completed"
    | "assessment_generated"
    | "blocked"
    | "failed";
  label: string;
  detail?: string;
  createdAt: string;
}

/** A node in the evidence graph (built only from real investigation data). */
export interface EvidenceGraphNode {
  id: string;
  kind: "claim" | "evidence" | "source" | "finding" | "assessment";
  label: string;
  evidenceId?: string;
}

export interface EvidenceGraphEdge {
  from: string;
  to: string;
  relation: "supports" | "contradicts" | "derived_from" | "verified_by" | "related_to";
}

export interface EvidenceGraph {
  nodes: EvidenceGraphNode[];
  edges: EvidenceGraphEdge[];
}

/** Serialized budget context used by the gateway when enforcing limits. */
export interface BudgetContext {
  maxPerEvidenceCheck: number;
  maxPerInvestigation: number;
  sessionBudget: number;
  totalBudget: number;
  /** Already settled spend for this investigation (micro USDC). */
  investigationSpent: number;
  /** Already settled spend for this session (micro USDC); smallest bucket that applies. */
  sessionSpent: number;
  /** Already settled spend overall (micro USDC). */
  totalSpent: number;
}

export interface BudgetDecision {
  allowed: boolean;
  reason?: "per_evidence" | "per_investigation" | "session_budget" | "total_budget";
  amountMicro: number;
  limitMicro: number;
  remainingMicro: number;
}
