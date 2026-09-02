import { NextRequest, NextResponse } from "next/server";
import { nanoid } from "nanoid";
import { getCurrentUser } from "../auth";
import {
  ORCHESTRATOR_CONFIG,
  ALGORAND_CONFIG,
  getPaidCapability,
  type PaidCapability,
} from "../config";
import { getInvestigationByIdempotencyKey, getInvestigation, saveInvestigation, savePayment } from "../db";
import {
  gatePaidRequest,
  type GatewayGate,
} from "./resourceServer";
import {
  sanitizeText,
  sanitizeUrl,
  storeFile,
  validateUpload,
} from "../storage";
import type { InvestigationInput } from "../types";

const SETTLEMENT_HEADER_NAMES = [
  "x-payment-response",
  "x-x402-payment",
  "x-payment",
  "Payment-Response",
];

export function extractSettlementTxId(res: Response): string {
  for (const name of SETTLEMENT_HEADER_NAMES) {
    const header = res.headers.get(name);
    if (!header) continue;
    try {
      const decoded = JSON.parse(
        Buffer.from(header, "base64").toString("utf-8")
      ) as { settleTxnId?: string; txId?: string; txnId?: string };
      return decoded?.settleTxnId ?? decoded?.txId ?? decoded?.txnId ?? "";
    } catch {
      // Try raw JSON (some facilitators use plain JSON, not base64)
      try {
        const parsed = JSON.parse(header) as {
          settleTxnId?: string;
          txId?: string;
          txnId?: string;
        };
        return parsed?.settleTxnId ?? parsed?.txId ?? parsed?.txnId ?? "";
      } catch {
        // not a payment-response header; keep scanning
      }
    }
  }
  return "";
}

export interface ParsedBody {
  question: string;
  url: string;
  text: string;
  files: { file: File; inputType: string }[];
}

/** Generic multipart/JSON body parser shared by all atomic routes. */
export async function parseBody(request: NextRequest): Promise<ParsedBody> {
  const contentType = request.headers.get("content-type") ?? "";
  let question = "";
  let url = "";
  let text = "";
  const files: { file: File; inputType: string }[] = [];

  if (contentType.includes("multipart/form-data")) {
    const formData = await request.formData();
    question = sanitizeText((formData.get("question") as string) ?? "");
    url = (formData.get("url") as string) ?? "";
    text = sanitizeText((formData.get("text") as string) ?? "");

    const rawFiles = formData.getAll("files") as File[];
    for (const file of rawFiles) {
      if (!file || file.size === 0) continue;
      const validation = validateUpload(file.type, file.size);
      if (!validation.valid) {
        throw new InputValidationError(validation.error ?? "Invalid file");
      }
      const inputType = mimeToInputType(file.type);
      files.push({ file, inputType });
    }
  } else {
    const body = await request.json().catch(() => ({})) as Record<string, unknown>;
    question = sanitizeText((body.question as string) ?? "");
    url = (body.url as string) ?? "";
    text = sanitizeText((body.text as string) ?? "");
  }

  return { question, url, text, files };
}

function mimeToInputType(mime: string): string {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (mime === "application/pdf") return "document";
  if (mime.includes("json") || mime.includes("csv")) return "data";
  return "document";
}

/** Map files + metadata to InvestigationInput[] stored on disk. */
export async function buildStoredInputs(
  parsed: ParsedBody,
  caseId: string
): Promise<InvestigationInput[]> {
  const inputs: InvestigationInput[] = [];

  if (parsed.url) {
    const sanitized = sanitizeUrl(parsed.url);
    if (sanitized) inputs.push({ type: "url", content: sanitized });
  }
  if (parsed.text) {
    inputs.push({ type: "text", content: parsed.text });
  }

  for (const { file, inputType } of parsed.files) {
    const buffer = Buffer.from(await file.arrayBuffer());
    const stored = await storeFile(buffer, file.name, file.type, caseId);
    inputs.push({
      type: inputType as InvestigationInput["type"],
      content: file.name,
      fileName: stored.fileName,
      mimeType: stored.mimeType,
      filePath: stored.filePath,
    });
  }

  return inputs;
}

export class InputValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputValidationError";
  }
}

export interface AtomicRouteOptions {
  /** Stable capability id (e.g. "claim-investigation"). */
  capabilityId: string;
  /** Capability-specific validation and orchestration. */
  run: (args: {
    id: string;
    userId: string;
    question: string;
    inputs: InvestigationInput[];
    idempotencyKey?: string;
  }) => Promise<{ id: string; status: string }>;
  /** Optional capability-specific input assembly (instead of buildStoredInputs). */
  assembleInputs?: (
    parsed: ParsedBody,
    caseId: string
  ) => Promise<InvestigationInput[]>;
}

/**
 * Shared handler for all atomic x402-paid investigation routes. Implements:
 *  1. Authentication (must be logged in).
 *  2. Idempotency (Idempotency-Key header → skip re-run).
 *  3. Body parsing and file storage.
 *  4. x402 payment gate via the capability's own resource server.
 *  5. Capability execution.
 *  6. Settlement finalization + merchant PaymentRecord (with capability id).
 */
export async function handleAtomicPaidRequest(
  opts: AtomicRouteOptions,
  request: NextRequest
): Promise<NextResponse> {
  const { capabilityId, run, assembleInputs } = opts;

  try {
    // ── 1. Auth ────────────────────────────────────────────────────────
    const user = await getCurrentUser();
    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const cap = getPaidCapability(capabilityId);
    if (!cap) {
      return NextResponse.json(
        { error: `Unknown capability: ${capabilityId}` },
        { status: 400 }
      );
    }

    // ── 2. Idempotency ────────────────────────────────────────────────
    const idempotencyKey = request.headers.get("idempotency-key")?.trim() || undefined;
    if (idempotencyKey) {
      const existing = await getInvestigationByIdempotencyKey(idempotencyKey, user.id);
      if (existing) {
        return NextResponse.json({
          id: existing.id,
          status: existing.status,
          capability: capabilityId,
          idempotent: true,
        });
      }
    }

    // ── 3. Parse & store inputs ───────────────────────────────────────
    let parsed: ParsedBody;
    try {
      parsed = await parseBody(request);
    } catch (err) {
      if (err instanceof InputValidationError) {
        return NextResponse.json({ error: err.message }, { status: 400 });
      }
      throw err;
    }

    if (!parsed.question?.trim()) {
      return NextResponse.json({ error: "Question is required" }, { status: 400 });
    }

    const caseId = `case_${nanoid(10)}`;
    const inputs = assembleInputs
      ? await assembleInputs(parsed, caseId)
      : await buildStoredInputs(parsed, caseId);

    // ── 4. x402 payment gate (capability-specific resource server) ────
    const gate = await gatePaidRequest(capabilityId, request);
    if (!gate.ok) {
      const gateResponse = gate.response ?? new Response("Payment required", { status: 402 });
      return new NextResponse(gateResponse.body, {
        status: gateResponse.status,
        headers: gateResponse.headers,
      });
    }

    // ── 5. Capability execution ───────────────────────────────────────
    const result = await run({
      id: caseId,
      userId: user.id,
      question: parsed.question.trim(),
      inputs,
      idempotencyKey,
    });

    // ── 6. Settlement + merchant fee record ──────────────────────────
    const res = await gate.settle({
      id: result.id,
      status: result.status,
      capability: capabilityId,
    });

    const txId = extractSettlementTxId(res);
    if (txId) {
      await savePayment({
        id: `pay_${nanoid(8)}`,
        investigationId: result.id,
        providerId: ORCHESTRATOR_CONFIG.payTo || "merchant",
        capability: capabilityId,
        amount: cap.priceUsdc,
        currency: "USDC",
        network: ALGORAND_CONFIG.network,
        protocol: "x402",
        status: "settled",
        settlementRef: txId,
        timestamp: new Date().toISOString(),
      });
    }

    // Restore the capabilitiesPaid field set by the capability handler (it was
    // overwritten by settle's plain clone in the response body).
    const inv = await getInvestigation(result.id);
    if (inv && !inv.capability) {
      inv.capability = capabilityId;
      inv.capabilityPriceUsdc = cap.priceUsdc;
      if (idempotencyKey) inv.idempotencyKey = idempotencyKey;
      await saveInvestigation(inv);
    }

    return res as unknown as NextResponse;
  } catch (err) {
    console.error(`[${capabilityId}] handler error:`, err);
    if (err instanceof InputValidationError) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    return NextResponse.json(
      { error: "Failed to process investigation" },
      { status: 500 }
    );
  }
}