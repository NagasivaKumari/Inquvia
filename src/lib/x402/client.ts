import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { ExactAvmScheme } from "@x402/avm/exact/client";
import { API_BASE, ALGORAND_NETWORK_CAIP2 } from "../config";
import { createX402Signer } from "../wallet/x402Signer";
import { apiFetch } from "../api";

function buildPaidFetch(address: string) {
  const signer = createX402Signer(address);
  const scheme = new ExactAvmScheme(signer);
  const client = new x402Client()
    .register("algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", scheme)
    .register("algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=", scheme);
  return wrapFetchWithPayment(apiFetch as typeof fetch, client);
}

export const SETTLEMENT_HEADER_NAMES = [
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
      const settle = decodePaymentResponseHeader(header) as {
        settleTxnId?: string;
        txId?: string;
        txnId?: string;
      };
      return settle?.settleTxnId ?? settle?.txId ?? settle?.txnId ?? "";
    } catch {
      // not a payment-response header; keep scanning
    }
  }
  return "";
}

export interface PaidInvestigationResult {
  id: string;
  status: string;
  txId: string;
  capability?: string;
}

/**
 * Pay for any atomic x402 investigation capability from the browser wallet.
 *
 * When `files` are provided, the body is sent as FormData (multipart) so the
 * server can store the uploaded files. When only text/url/question is supplied,
 * JSON is sent. The wrapped fetch handles the 402 → sign → facilitator settle
 * → retry flow automatically.
 */
export async function payForCapability(input: {
  address: string;
  endpoint: string;
  question: string;
  text?: string;
  url?: string;
  files?: File[];
  idempotencyKey?: string;
}): Promise<PaidInvestigationResult> {
  const fetchWithPay = buildPaidFetch(input.address);

  let headers: Record<string, string> = {};
  let body: BodyInit;

  if (input.files && input.files.length > 0) {
    const fd = new FormData();
    fd.append("question", input.question);
    if (input.text) fd.append("text", input.text);
    if (input.url) fd.append("url", input.url);
    for (const file of input.files) {
      fd.append("files", file);
    }
    body = fd;
  } else {
    headers = { "Content-Type": "application/json" };
    body = JSON.stringify({
      question: input.question,
      text: input.text,
      url: input.url,
    });
  }

  const requestHeaders = new Headers(headers);
  if (input.idempotencyKey) {
    requestHeaders.set("Idempotency-Key", input.idempotencyKey);
  }

  const endpointUrl = input.endpoint.startsWith("http")
    ? input.endpoint
    : `${API_BASE}${input.endpoint.startsWith("/") ? "" : "/"}${input.endpoint}`;

  const res = await fetchWithPay(endpointUrl, {
    method: "POST",
    headers: requestHeaders,
    body,
  });

  if (!res.ok) {
    throw new Error(`Investigation endpoint returned ${res.status}`);
  }

  const txId = extractSettlementTxId(res);
  const bodyJson = (await res.json().catch(() => ({}))) as {
    id?: string;
    status?: string;
    capability?: string;
  };
  if (!bodyJson.id) {
    throw new Error("Investigation did not return an id");
  }
  return {
    id: bodyJson.id,
    status: bodyJson.status ?? "",
    txId,
    capability: bodyJson.capability,
  };
}

/**
 * Legacy wrapper: pay for the unified /api/investigate endpoint (if still used).
 * Kept for backward compatibility; new code should call payForCapability directly.
 */
export async function payForInvestigation(input: {
  address: string;
  question: string;
  text?: string;
  url?: string;
}): Promise<PaidInvestigationResult> {
  const fetchWithPay = buildPaidFetch(input.address);

  const res = await fetchWithPay("/api/investigate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: input.question,
      text: input.text,
      url: input.url,
      from: input.address,
    }),
  });

  if (!res.ok) {
    throw new Error(`Investigation endpoint returned ${res.status}`);
  }

  const txId = extractSettlementTxId(res);
  const body = (await res.json().catch(() => ({}))) as {
    id?: string;
    status?: string;
  };
  if (!body.id) {
    throw new Error("Investigation did not return an id");
  }
  return { id: body.id, status: body.status ?? "", txId };
}

/** Determine the correct atomic endpoint for a set of inputs. */
export function detectCapabilityEndpoint(files: File[], url: string): string {
  const mimes = files.map((f) => f.type);
  if (mimes.some((m) => m.startsWith("image/"))) return "/api/x402/image-investigation";
  if (mimes.some((m) => m.startsWith("video/"))) return "/api/x402/video-investigation";
  if (mimes.some((m) => m === "application/pdf")) return "/api/x402/document-investigation";
  if (mimes.some((m) => m.includes("json") || m.includes("csv"))) return "/api/x402/data-investigation";
  if (url?.trim()) return "/api/x402/source-investigation";
  return "/api/x402/claim-investigation";
}
