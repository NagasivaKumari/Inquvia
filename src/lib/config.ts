/** Central application configuration — brand name is configurable here. */

export const APP_NAME = process.env.APP_NAME ?? "Inquvia";

/** Base URL for the FastAPI backend. Empty = same-origin (dev proxy / Vercel rewrite). */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

export const TAGLINE = "Investigate before you decide.";

export const SUBHEADLINE =
  "Something looks suspicious, confusing, or too good to be true? Give it to Inquvia and get an evidence-backed assessment instead of a guess.";

export const ALGORAND_CONFIG = {
  // NEXT_PUBLIC_ALGORAND_NETWORK is inlined into client bundles so the network
  // label renders identically on server and client (avoids hydration mismatch).
  network:
    process.env.NEXT_PUBLIC_ALGORAND_NETWORK ??
    process.env.ALGORAND_NETWORK ??
    "mainnet",
  usdcAsa: process.env.ALGORAND_USDC_ASA ?? "31566704",
  facilitatorUrl:
    process.env.X402_FACILITATOR_URL ?? "https://facilitator.goplausible.xyz",
  challengeTag: process.env.X402_CHALLENGE_TAG ?? "x402-global-challenge",
  // Algorand node (algod) used to submit signed transactions on-chain.
  // Defaults to the free public Algonode API — set your own for production.
  algodToken: process.env.ALGOD_TOKEN ?? "",
  algodServer:
    (process.env.ALGOD_SERVER && process.env.ALGOD_SERVER.trim()) ||
    (process.env.ALGORAND_NETWORK === "testnet" || process.env.NEXT_PUBLIC_ALGORAND_NETWORK === "testnet"
      ? "https://testnet-api.algonode.cloud"
      : "https://mainnet-api.algonode.cloud"),
  algodPort: process.env.ALGOD_PORT ? Number(process.env.ALGOD_PORT) : 443,
} as const;

/** CAIP-2 network id matching ALGORAND_CONFIG.network. */
export const ALGORAND_NETWORK_CAIP2 =
  ALGORAND_CONFIG.network === "testnet"
    ? "algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI="
    : "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=";

/**
 * Evidence Acquisition Gateway configuration.
 *
 * Real external evidence services are discovered in one of two ways:
 *  1. EXTERNAL_EVIDENCE_SERVICES_URL — a facilitator/Bazaar discovery catalog
 *     JSON endpoint that returns x402-protected evidence services with the
 *     configured challenge tag. When set, discovery queries it live.
 *  2. EXTERNAL_EVIDENCE_SERVICES_JSON — a comma/newline-separated inline catalog
 *     of one or more evidence services (name|url|capabilities|price_usdc).
 *
 * If neither is configured, discovery returns NO services and new
 * investigations requiring external evidence enter the `evidence_unavailable`
 * state. No fake providers are ever invented.
 */
export const EVIDENCE_GATEWAY_CONFIG = {
  discoveryUrl: process.env.EXTERNAL_EVIDENCE_SERVICES_URL ?? "",
  inlineCatalog: process.env.EXTERNAL_EVIDENCE_SERVICES_JSON ?? "",
  discoveryTag: process.env.X402_CHALLENGE_TAG ?? "x402-global-challenge",
} as const;

/**
 * Inquvia merchant-side config.
 *
 * Inquvia exposes multiple genuinely independent atomic x402-paid
 * investigation capabilities (see PAID_CAPABILITIES below). All of them
 * share ONE payTo address and settle through the same GoPlausible
 * facilitator on Algorand. Inquvia's backend may additionally pay downstream
 * evidence services from its own wallet.
 */
export const ORCHESTRATOR_CONFIG = {
  /** Inquvia's single USDC receiving address for ALL paid capabilities. */
  payTo: process.env.INQUVIA_PAYTO_ADDRESS ?? "",
  /** Optional server wallet mnemonic used to pay downstream evidence services. */
  serverWalletMnemonic: process.env.SERVER_WALLET_MNEMONIC ?? "",
} as const;

function priceEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export interface PaidCapability {
  /** Stable capability id (also recorded on investigations/payments). */
  id: string;
  /** Human title shown in the UI. */
  title: string;
  /** Independent x402 resource path — each is independently callable/priced. */
  endpoint: string;
  /** Price in whole USDC dollars for this atomic capability. */
  priceUsdc: number;
  /** Bazaar discovery description (must match what the endpoint actually does). */
  description: string;
  /** Input kinds this capability genuinely accepts. */
  inputTypes: readonly string[];
}

/**
 * Inquvia's COMPOSITE x402 capability set. Every entry is a real, atomic,
 * independently callable paid endpoint. They share the same payTo address and
 * each has its own price. Prices are per-endpoint because each capability does
 * genuinely different work (multimodal analysis, live web inspection, etc.).
 */
export const PAID_CAPABILITIES: readonly PaidCapability[] = [
  {
    id: "claim-investigation",
    title: "Claim Investigation",
    endpoint: "/api/x402/claim-investigation",
    priceUsdc: priceEnv("CLAIM_INVESTIGATION_PRICE_USDC", 0.005),
    description:
      "Check whether a claim is supported by available evidence.",
    inputTypes: ["text"],
  },
  {
    id: "image-investigation",
    title: "Image Investigation",
    endpoint: "/api/x402/image-investigation",
    priceUsdc: priceEnv("IMAGE_INVESTIGATION_PRICE_USDC", 0.008),
    description:
      "Investigate an image for context, provenance, and evidence.",
    inputTypes: ["image"],
  },
  {
    id: "video-investigation",
    title: "Video Investigation",
    endpoint: "/api/x402/video-investigation",
    priceUsdc: priceEnv("VIDEO_INVESTIGATION_PRICE_USDC", 0.015),
    description:
      "Investigate what a video shows and whether its context holds up.",
    inputTypes: ["video"],
  },
  {
    id: "document-investigation",
    title: "Document Investigation",
    endpoint: "/api/x402/document-investigation",
    priceUsdc: priceEnv("DOCUMENT_INVESTIGATION_PRICE_USDC", 0.007),
    description:
      "Examine a document for findings, inconsistencies, and evidence.",
    inputTypes: ["document"],
  },
  {
    id: "source-investigation",
    title: "Source Investigation",
    endpoint: "/api/x402/source-investigation",
    priceUsdc: priceEnv("SOURCE_INVESTIGATION_PRICE_USDC", 0.006),
    description:
      "Investigate a website or source before you trust it.",
    inputTypes: ["url"],
  },
  {
    id: "data-investigation",
    title: "Data Investigation",
    endpoint: "/api/x402/data-investigation",
    priceUsdc: priceEnv("DATA_INVESTIGATION_PRICE_USDC", 0.012),
    description:
      "Investigate structured data for anomalies and supporting signals.",
    inputTypes: ["data"],
  },
] as const;

/** Return a capability descriptor by id, or undefined. */
export function getPaidCapability(
  id: string
): PaidCapability | undefined {
  return PAID_CAPABILITIES.find((c) => c.id === id);
}

export const DATABASE_PATH =
  process.env.DATABASE_PATH ?? "./data/inquvia.db";

export const STORAGE_PATH =
  process.env.STORAGE_PATH ?? "./data/uploads";

export const MAX_UPLOAD_SIZE = 10 * 1024 * 1024; // 10MB

export const ALLOWED_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "video/mp4",
  "video/webm",
  "application/pdf",
  "text/plain",
  "text/csv",
  "application/json",
] as const;

export const EXAMPLE_PROMPTS = [
  "Is this seller legitimate?",
  "Is this job offer genuine?",
  "Is this image authentic?",
  "Can I trust this website?",
  "Is this video being taken out of context?",
  "Does this document look suspicious?",
  "Does this claim have reliable evidence?",
] as const;

export const INVESTIGATION_STAGES = [
  { id: "created", label: "Investigating" },
  { id: "planning", label: "Planning investigation" },
  { id: "discovering", label: "Discovering evidence services" },
  { id: "awaiting_payment", label: "Payment required" },
  { id: "payment_pending", label: "Payment pending" },
  { id: "evidence_requested", label: "Acquiring evidence" },
  { id: "evidence_received", label: "Evidence received" },
  { id: "analyzing", label: "Analyzing evidence" },
  { id: "cross_checking", label: "Cross-checking evidence" },
  { id: "assessment", label: "Final assessment" },
] as const;

export type InvestigationStageId =
  (typeof INVESTIGATION_STAGES)[number]["id"];

export type StageStatus = "pending" | "active" | "completed" | "failed";

/** Investigation statuses that are terminal failures (evidence could not be acquired). */
export const INVESTIGATION_BLOCKED_STATES = [
  "payment_failed",
  "settlement_failed",
  "evidence_unavailable",
  "blocked",
  "failed",
] as const;

export const NAV_ITEMS = [
  { href: "/investigate", label: "Investigate" },
  { href: "/history", label: "History" },
  { href: "/reports", label: "Reports" },
  { href: "/activity", label: "Activity" },
  { href: "/settings", label: "Settings" },
] as const;

/** Public site navigation — used by header, footer, and mobile drawer. */
export const PUBLIC_NAV = [
  { href: "/how-it-works", label: "How It Works" },
  { href: "/#capabilities", label: "What You Can Check" },
] as const;

export const FOOTER_COLUMNS = [
  {
    title: "Product",
    links: [
      ["How It Works", "/how-it-works"],
      ["Investigate", "/investigate"],
      ["What You Can Check", "/#capabilities"],
      ["Evidence", "/#evidence"],
      ["x402", "/#x402"],
    ] as [string, string][],
  },
  {
    title: "Account",
    links: [
      ["Sign In", "/login"],
      ["Register", "/signup"],
    ] as [string, string][],
  },
  {
    title: "Technology",
    links: [
      ["Algorand", "https://algorand.com"],
      ["x402", "https://x402.org"],
    ] as [string, string][],
  },
] as const;

/** Real-life situations ordinary people check before they decide. */
export const CONSUMER_CASES = [
  {
    title: "Online shopping",
    question: "Is this seller legitimate?",
  },
  {
    title: "Job offers",
    question: "Is this recruiter or offer genuine?",
  },
  {
    title: "Social media",
    question: "Is this claim being presented honestly?",
  },
  {
    title: "Images",
    question: "Is this image authentic or misleading?",
  },
  {
    title: "Websites",
    question: "Can I trust this site?",
  },
  {
    title: "Documents",
    question: "Does this document contain inconsistencies?",
  },
] as const;

/** "Before you click/buy/believe" decision moments shown as a story. */
export const DECISION_MOMENTS = [
  {
    before: "See a suspicious listing",
    action: "investigate",
  },
  {
    before: "Receive an unusual job offer",
    action: "investigate",
  },
  {
    before: "See a viral image",
    action: "investigate",
  },
  {
    before: "Find an unfamiliar website",
    action: "investigate",
  },
  {
    before: "Receive a questionable document",
    action: "investigate",
  },
] as const;

export const PROCESS_STEPS = [
  {
    n: "01",
    title: "Bring the question",
    detail: "Ask anything you're unsure about.",
  },
  {
    n: "02",
    title: "Tell Inquvia what you have",
    detail: "Add a claim, image, video, document, URL, or data.",
  },
  {
    n: "03",
    title: "Inquvia investigates",
    detail: "The system determines what needs to be checked.",
  },
  {
    n: "04",
    title: "See the evidence",
    detail: "Find supporting evidence, contradictions, confidence, and gaps.",
  },
  {
    n: "05",
    title: "Decide with more context",
    detail: "Get a clear assessment without pretending uncertainty does not exist.",
  },
] as const;

export const PIPELINE_STEPS = [
  {
    title: "Submit an investigation",
    detail: "The client asks a question or selects a service, then calls the investigation API.",
  },
  {
    title: "Payment required (HTTP 402)",
    detail: "The paid endpoint demands settlement before any work begins.",
  },
  {
    title: "Client pays the orchestrator",
    detail: `The browser wallet signs the x402 payment to ${APP_NAME}'s USDC address through the facilitator.`,
  },
  {
    title: "Facilitator verifies and settles",
    detail: "The facilitator verifies and settles the micro-payment on Algorand.",
  },
  {
    title: "Paid request is accepted",
    detail: "On-chain settlement is confirmed and the investigation is accepted.",
  },
  {
    title: "Investigation planner",
    detail: "The agent determines what verifiable evidence is required for this claim.",
  },
  {
    title: "Service discovery",
    detail: "External evidence services are discovered from the configured x402 catalog.",
  },
  {
    title: "Select evidence services",
    detail: "Paid evidence endpoints are chosen within the enforced budget.",
  },
  {
    title: "Downstream x402 payments",
    detail: `${APP_NAME} pays each evidence service from its own wallet when a real service is available.`,
  },
  {
    title: "Evidence returned",
    detail: "Each paid service returns evidence settled on-chain. Nothing is fabricated.",
  },
  {
    title: "Cross-check and reasoning",
    detail: "Independent sources are compared for contradiction and consensus.",
  },
  {
    title: "Evidence-backed result",
    detail: "A citation-backed dossier with confidence and an on-chain payment trail.",
  },
] as const;

/**
 * Real consumer-oriented imagery (Unsplash, licensed). Override via
 * NEXT_PUBLIC_MEDIA_* if you host your own photographs. Each relates to an
 * everyday "is this real?" decision, not an office/corporate scene.
 */
export const MEDIA = {
  hero:
    process.env.NEXT_PUBLIC_MEDIA_HERO ??
    "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=1600&q=80",
  heroAlt: "Person reviewing something on a screen before deciding",
  shopping:
    process.env.NEXT_PUBLIC_MEDIA_SHOPPING ??
    "https://images.unsplash.com/photo-1483985988355-763728e1935b?auto=format&fit=crop&w=1400&q=80",
  shoppingAlt: "A shopping listing under review",
  website:
    process.env.NEXT_PUBLIC_MEDIA_WEBSITE ??
    "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1400&q=80",
  websiteAlt: "A website open in a browser window",
  joboffer:
    process.env.NEXT_PUBLIC_MEDIA_JOB ??
    "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1400&q=80",
  jobofferAlt: "A message that could be a job offer",
  document:
    process.env.NEXT_PUBLIC_MEDIA_DOCUMENT ??
    "https://images.unsplash.com/photo-1586281380349-632531db7ed4?auto=format&fit=crop&w=1400&q=80",
  documentAlt: "A document being examined for inconsistencies",
  image:
    process.env.NEXT_PUBLIC_MEDIA_IMAGE ??
    "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1400&q=80",
  imageAlt: "An image investigated for authenticity",
} as const;

export function capabilityTitle(idOrPath: string): string {
  const id = idOrPath.replace(/^\/api\/x402\//, "");
  return getPaidCapability(id)?.title ?? idOrPath;
}
