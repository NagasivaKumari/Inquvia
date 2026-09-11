import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { ExactAvmScheme } from "@x402/avm/exact/client";
import type { PaymentRequirements, PaymentPayloadResult } from "@x402/core/types";
import algosdk from "algosdk";
import { API_BASE, ALGORAND_NETWORK_CAIP2, ALGORAND_CONFIG } from "../config";
import { createX402Signer } from "../wallet/x402Signer";
import { apiFetch } from "../api";

type X402Signer = ConstructorParameters<typeof ExactAvmScheme>[0];

/**
 * The published ExactAvmScheme.createPaymentPayload rebuilds each txn through
 * @algorandfoundation/algokit-utils (bundled alpha), whose msgpack codec drops
 * sender/amount and the signature during encode → the facilitator rejects the
 * group ("Unsigned transaction from non-facilitator address"). This subclass
 * rebuilds the identical group with plain algosdk (canonical wire format);
 * verified against the live facilitator (now only fails on funding/opt-in).
 */
class AlgodExactAvmScheme extends ExactAvmScheme {
  private readonly userSigner: X402Signer;

  constructor(signer: X402Signer) {
    super(signer);
    this.userSigner = signer;
  }

  private async fetchTransactionParams(): Promise<AlgodTxnParams> {
    const res = await fetch(`${API_BASE}/api/x402/transaction-params`, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Transaction params unavailable (HTTP ${res.status})`);
    }
    return (await res.json()) as AlgodTxnParams;
  }

  override async createPaymentPayload(
    x402Version: number,
    requirements: PaymentRequirements
  ): Promise<PaymentPayloadResult> {
    const { amount, asset, payTo, extra } = requirements;
    const feePayer = (extra?.feePayer ?? undefined) as string | undefined;
    const sp = await this.fetchTransactionParams();
    emitPay("payment-params-ready", { feePayer: !!feePayer });
    const feePerByte = Number(sp.fee);
    const minFee = Number(sp.minFee || 1000);
    const suggestedParams = {
      fee: feePerByte,
      firstValid: Number(sp.firstRound),
      lastValid: Number(sp.lastRound),
      genesisHash: sp.genesisHash
        ? Uint8Array.from(Buffer.from(sp.genesisHash, "base64"))
        : undefined,
      genesisId: sp.genesisId,
      minFee,
      flatFee: false,
    };
    const encodeNote = (s: string) => new TextEncoder().encode(s);
    const assetId = BigInt(
      /^\d+$/.test(asset) ? asset : ALGORAND_CONFIG.usdcAsa
    );
    const now = Date.now();
    const notePay = encodeNote(`x402-payment-v${x402Version}-${now}`);

    const makeTransfer = (fee: bigint, flat: boolean) =>
      algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
        sender: this.userSigner.address,
        receiver: payTo,
        amount: BigInt(amount),
        assetIndex: assetId,
        note: notePay,
        suggestedParams: { ...suggestedParams, fee: Number(fee), flatFee: flat },
      });

    let transactions: algosdk.Transaction[];
    let paymentIndex = 0;
    if (feePayer) {
      const makePayer = (fee: bigint) =>
        algosdk.makePaymentTxnWithSuggestedParamsFromObject({
          sender: feePayer,
          receiver: feePayer,
          amount: BigInt(0),
          note: encodeNote(`x402-fee-payer-${now}`),
          suggestedParams: { ...suggestedParams, fee: Number(fee), flatFee: true },
        });
      const preliminary = [
        makePayer(BigInt(minFee)),
        makeTransfer(BigInt(0), true),
      ];
      const total = preliminary.reduce(
        (sum, tx) =>
          sum +
          BigInt(
            feePerByte > 0
              ? Math.max(
                  feePerByte * algosdk.encodeUnsignedTransaction(tx).length,
                  minFee
                )
              : minFee
          ),
        BigInt(0)
      );
      transactions = [makePayer(total), makeTransfer(BigInt(0), true)];
      paymentIndex = 1;
    } else {
      transactions = [makeTransfer(BigInt(feePerByte), false)];
    }

    const gid = algosdk.computeGroupID(transactions);
    transactions.forEach((tx) => {
      tx.group = gid;
    });

    const encoded = transactions.map((tx) => algosdk.encodeUnsignedTransaction(tx));
    const clientIndexes = transactions
      .map((tx, i) => (tx.sender.toString() === this.userSigner.address ? i : -1))
      .filter((i) => i !== -1);
    const signed = await this.userSigner.signTransactions(encoded, clientIndexes);

    const paymentGroup = encoded.map((bytes, i) => {
      const s = signed[i];
      return Buffer.from(s ?? bytes).toString("base64");
    });

    return { x402Version, payload: { paymentGroup, paymentIndex } };
  }
}

interface AlgodTxnParams {
  fee: number;
  minFee: number;
  firstRound: number;
  lastRound: number;
  genesisHash?: string;
  genesisId?: string;
}

/** Dispatch a diagnostic event so pages can surface the exact payment step. */
function emitPay(step: string, extra?: Record<string, unknown>) {
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent("inquvia:pay-diagnostic", { detail: { step, ...extra } })
    );
  }
}

/** Fetch suggested params through the backend (no direct browser algod). */
async function fetchTransactionParams(): Promise<AlgodTxnParams> {
  const res = await fetch(`${API_BASE}/api/x402/transaction-params`, {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Transaction params unavailable (HTTP ${res.status})`);
  }
  return (await res.json()) as AlgodTxnParams;
}

/**
 * Make sure the paying wallet is opted into USDC before the payment is built.
 * Opting-in is a self asset-transfer of 0, signed via Pera and broadcast
 * through the backend (browser-direct algod calls fail silently — the bug the
 * /api/x402 proxy endpoints exist to avoid).
 */
async function ensureUsdcOptIn(address: string): Promise<void> {
  let status: { optedIn: boolean; balance: number };
  try {
    const res = await fetch(
      `${API_BASE}/api/x402/account-status?address=${encodeURIComponent(address)}`,
      { credentials: "include", cache: "no-store" }
    );
    if (!res.ok) throw new Error(`account-status HTTP ${res.status}`);
    status = await res.json();
  } catch {
    // Status check is best-effort; if it fails, let the payment attempt and
    // surface the simulation error instead of hard-blocking.
    return;
  }

  if (status.optedIn) {
    if (status.balance <= 0) {
      const message =
        "Connected wallet is opted into USDC but holds 0 USDC on testnet — fund it " +
        "(e.g. via the Pera faucet / 10 USDC from a funded account) before paying.";
      emitPay("error", { message });
      throw new Error(message);
    }
    return;
  }

  emitPay("opt-in-required", { address });
  const { ensurePeraSession, getPera } = await import("@/lib/wallet/pera");
  const sp = await fetchTransactionParams();
  const txn = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: address,
    receiver: address,
    amount: 0,
    assetIndex: Number(ALGORAND_CONFIG.usdcAsa),
    suggestedParams: {
      fee: Number(sp.fee),
      firstValid: Number(sp.firstRound),
      lastValid: Number(sp.lastRound),
      genesisHash: sp.genesisHash
        ? Uint8Array.from(Buffer.from(sp.genesisHash, "base64"))
        : undefined,
      genesisID: sp.genesisId,
      minFee: Number(sp.minFee || 1000),
      flatFee: false,
    },
  });
  const pera = await ensurePeraSession();
  const signed = await pera.signTransaction([[{ txn, signers: [address] }]]);
  const blob = Buffer.from(signed[0]).toString("base64");
  const broadcast = await fetch(`${API_BASE}/api/x402/broadcast`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signedTxn: blob }),
  });
  if (!broadcast.ok) {
    throw new Error(
      "USDC opt-in signed but broadcast failed — try again in a few seconds."
    );
  }
  emitPay("opt-in-ready");
}

function buildPaidFetch(address: string) {
  const signer = createX402Signer(address);
  const scheme = new AlgodExactAvmScheme(signer);
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
  serviceName?: string;
  text?: string;
  url?: string;
  files?: File[];
  idempotencyKey?: string;
  signal?: AbortSignal;
}): Promise<PaidInvestigationResult> {
  const fetchWithPay = buildPaidFetch(input.address);

  let headers: Record<string, string> = {};
  let body: BodyInit;

  if (input.files && input.files.length > 0) {
    const fd = new FormData();
    fd.append("question", input.question);
    if (input.text) fd.append("text", input.text);
    if (input.url) fd.append("url", input.url);
    if (input.serviceName) fd.append("serviceName", input.serviceName);
    for (const file of input.files) {
      fd.append("files", file);
    }
    body = fd;
  } else {
    headers = { "Content-Type": "application/json" };
    body = JSON.stringify({
      question: input.question,
      serviceName: input.serviceName,
      text: input.text,
      url: input.url,
    });
  }

  const requestHeaders = new Headers(headers);
  if (input.idempotencyKey) {
    requestHeaders.set("Idempotency-Key", input.idempotencyKey);
  }

  await ensureUsdcOptIn(input.address);

  const endpointUrl = input.endpoint.startsWith("http")
    ? input.endpoint
    : `${API_BASE}${input.endpoint.startsWith("/") ? "" : "/"}${input.endpoint}`;

  let res: Response;
  try {
    res = await fetchWithPay(endpointUrl, {
      method: "POST",
      headers: requestHeaders,
      body,
      signal: input.signal,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // Retry ONCE only when the payment step failed before a settle could be
    // recorded: a 402 from the server or a payment-build failure means no
    // money moved, so re-running the signed flow is safe (never double-pays).
    const canRetry = /402|payment.required|transaction.params|failed to pay|settle/i.test(message);
    if (!canRetry || input.signal?.aborted) {
      throw err;
    }
    emitPay("retrying-payment", { message });
    await new Promise((r) => setTimeout(r, 600));
    const retryFetch = buildPaidFetch(input.address);
    res = await retryFetch(endpointUrl, {
      method: "POST",
      headers: requestHeaders,
      body,
      signal: input.signal,
    });
  }

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
  const names = files.map((f) => f.name.toLowerCase());
  
  if (mimes.some((m) => m.startsWith("image/"))) return "/api/x402/image-investigation";
  
  if (mimes.some((m) => m.startsWith("video/")) || 
      names.some((n) => n.endsWith(".mp4") || n.endsWith(".mov") || n.endsWith(".avi") || n.endsWith(".wmv"))) {
    return "/api/x402/video-investigation";
  }
  
  if (mimes.some((m) => m === "application/pdf")) return "/api/x402/document-investigation";
  if (mimes.some((m) => m.includes("json") || m.includes("csv"))) return "/api/x402/data-investigation";
  if (mimes.some((m) => m.startsWith("audio/"))) return "/api/x402/audio-investigation";
  if (url?.trim()) return "/api/x402/source-investigation";
  return "/api/x402/claim-investigation";
}
