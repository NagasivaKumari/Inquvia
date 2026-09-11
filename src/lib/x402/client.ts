import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { ExactAvmScheme } from "@x402/avm/exact/client";
import { x402HTTPClient } from "@x402/core/http";
import type { PaymentRequirements, PaymentPayloadResult, PaymentPayload } from "@x402/core/types";
import algosdk from "algosdk";
import { API_BASE, ALGORAND_CONFIG } from "../config";
import { createX402Signer } from "../wallet/x402Signer";
import { apiFetch } from "../api";

type X402Signer = ConstructorParameters<typeof ExactAvmScheme>[0];

function toAtomicAmount(amount: string, extra?: Record<string, unknown>): bigint {
  const raw = String(amount ?? "").trim();
  if (/^\d+$/.test(raw)) return BigInt(raw);
  const decimals = Number(extra?.decimals ?? 6);
  const money = raw.replace(/^\$/, "").replace(/,/g, "");
  if (!/^\d+(\.\d+)?$/.test(money)) {
    throw new Error(`Invalid payment amount: ${amount}`);
  }
  const [whole, frac = ""] = money.split(".");
  const padded = (frac + "0".repeat(decimals)).slice(0, decimals);
  return BigInt(whole) * (BigInt(10) ** BigInt(decimals)) + BigInt(padded || "0");
}

function suggestedParamsFromAlgod(sp: AlgodTxnParams): algosdk.SuggestedParams {
  if (!sp.genesisHash) {
    throw new Error("Algod suggested params missing genesisHash");
  }
  return {
    fee: Number(sp.fee),
    firstValid: Number(sp.firstRound),
    lastValid: Number(sp.lastRound),
    genesisHash: algosdk.base64ToBytes(sp.genesisHash),
    genesisID: sp.genesisId,
    minFee: Number(sp.minFee || 1000),
    flatFee: false,
  };
}

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
    try {
      return await this.buildPaymentPayload(x402Version, requirements);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      emitPay("error", { message });
      throw err;
    }
  }

  private async buildPaymentPayload(
    x402Version: number,
    requirements: PaymentRequirements
  ): Promise<PaymentPayloadResult> {
    const { amount, asset, payTo, extra } = requirements;
    const feePayer = (extra?.feePayer ?? undefined) as string | undefined;
    const atomicAmount = toAtomicAmount(String(amount), extra);
    const sp = await this.fetchTransactionParams();
    emitPay("payment-params-ready", { feePayer: !!feePayer });
    const feePerByte = Number(sp.fee);
    const minFee = Number(sp.minFee || 1000);
    const suggestedParams = suggestedParamsFromAlgod(sp);
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
        amount: atomicAmount,
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
      return algosdk.bytesToBase64(s ?? bytes);
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
    suggestedParams: suggestedParamsFromAlgod(sp),
  });
  const pera = await ensurePeraSession();
  const signed = await pera.signTransaction([[{ txn, signers: [address] }]]);
  const blob = algosdk.bytesToBase64(signed[0]);
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

interface X402PaymentBundle {
  fetchWithPay: ReturnType<typeof wrapFetchWithPayment>;
  httpClient: x402HTTPClient;
}

function buildX402Payment(address: string, capabilityId?: string): X402PaymentBundle {
  const signer = createX402Signer(address, capabilityId);
  const scheme = new AlgodExactAvmScheme(signer);
  const client = new x402Client()
    .register("algorand:SGO1GKSzyE7IEPItTxCByw9x8FmnrCDexi9/cOUJOiI=", scheme)
    .register("algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=", scheme)
    // @x402/core defaults to a $1 cap, which silently drops every accept
    // before the wallet is prompted. Investigation price is server-gated.
    .setSpendControls(false);
  return { fetchWithPay: wrapFetchWithPayment(apiFetch as typeof fetch, client), httpClient: new x402HTTPClient(client) };
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
  const capabilityId = input.endpoint.split("/").pop();
  const { fetchWithPay, httpClient } = buildX402Payment(input.address, capabilityId);
  const hasFiles = !!input.files && input.files.length > 0;

  const buildBody = (): { headers: Record<string, string>; body: BodyInit } => {
    if (hasFiles) {
      const fd = new FormData();
      fd.append("question", input.question);
      if (input.text) fd.append("text", input.text);
      if (input.url) fd.append("url", input.url);
      if (input.serviceName) fd.append("serviceName", input.serviceName);
      for (const file of input.files ?? []) {
        fd.append("files", file);
      }
      return { headers: {}, body: fd };
    }
    return {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: input.question,
        serviceName: input.serviceName,
        text: input.text,
        url: input.url,
      }),
    };
  };

  const requestHeadersFor = (extra: Record<string, string>) => {
    const requestHeaders = new Headers(extra);
    if (input.idempotencyKey) {
      requestHeaders.set("Idempotency-Key", input.idempotencyKey);
    }
    return requestHeaders;
  };

  await ensureUsdcOptIn(input.address);

  const endpointUrl = input.endpoint.startsWith("http")
    ? input.endpoint
    : `${API_BASE}${input.endpoint.startsWith("/") ? "" : "/"}${input.endpoint}`;

  const call = (
    f: typeof fetchWithPay,
    headers: Record<string, string>,
    body: BodyInit
  ) =>
    f(endpointUrl, {
      method: "POST",
      headers: requestHeadersFor(headers),
      body,
      signal: input.signal,
    });

  let res: Response;
  if (hasFiles) {
    // Multipart bodies are single-use streams — wrapFetchWithPayment re-sends
    // the same drained FormData on retry (arrives empty). We do the
    // 402 → sign → retry handshake manually with a fresh body each round.
    emitPay("gate-rejected", { message: "Probing endpoint for payment requirements…" });
    res = await call(apiFetch as typeof fetchWithPay, {}, buildBody().body);

    if (res.status === 402) {
      emitPay("requesting-approval");
      let payload: PaymentPayload;
      try {
        const paymentRequired = httpClient.getPaymentRequiredResponse((name) => res.headers.get(name));
        payload = await httpClient.createPaymentPayload(paymentRequired);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        emitPay("error", { message: `Payment signing failed: ${message}` });
        throw new Error(`Payment signing failed: ${message}`);
      }
      emitPay("request-approved");

      // Retry the request with the signed payment header and a FRESH body
      const paymentHeader = httpClient.encodePaymentSignatureHeader(payload);
      res = await call(
        apiFetch as typeof fetchWithPay,
        { ...paymentHeader },
        buildBody().body // REBUILT FRESH
      );

      // If the library says the response needs one more round-trip, retry once
      const { recovered } = await httpClient
        .processPaymentResult(payload, (name) => res.headers.get(name), res.status)
        .catch(() => ({ recovered: false }));
      if (recovered) {
        emitPay("retrying-payment", { message: "Retrying after settlement recovery." });
        const paymentRequired = httpClient.getPaymentRequiredResponse((name) => res.headers.get(name));
        const freshPayload = await httpClient.createPaymentPayload(paymentRequired);
        res = await call(
          apiFetch as typeof fetchWithPay,
          { ...httpClient.encodePaymentSignatureHeader(freshPayload) },
          buildBody().body // REBUILT FRESH
        );
        await httpClient.processPaymentResult(
          freshPayload,
          (name) => res.headers.get(name),
          res.status
        );
      }
    }
  } else {
    try {
      res = await call(fetchWithPay, {}, buildBody().body);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      // The bare 402 is the expected first round of the x402 protocol — the
      // server asks "who pays?", then we retry with a signed payment header.
      emitPay("gate-rejected", { message });
      // Retry ONCE only when the payment step failed before a settle could be
      // recorded: a 402 from the server or a payment-build failure means no
      // money moved, so re-running the signed flow is safe (never double-pays).
      const canRetry = /402|payment.required|transaction.params|failed to (create )?pay|payload|settle/i.test(message);
      if (!canRetry || input.signal?.aborted) {
        throw err;
      }
      emitPay("retrying-payment", { message });
      await new Promise((r) => setTimeout(r, 600));
      res = await call(buildX402Payment(input.address).fetchWithPay, {}, buildBody().body);
    }
  }

  if (!res.ok) {
    const required = res.headers.get("PAYMENT-REQUIRED") || res.headers.get("payment-required");
    let reason = "";
    if (required) {
      try {
        const decoded = JSON.parse(atob(required)) as { error?: string };
        reason = decoded.error ? `: ${decoded.error}` : "";
      } catch {
        reason = "";
      }
    }
    throw new Error(`Investigation endpoint returned ${res.status}${reason}`);
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
  const fetchWithPay = buildX402Payment(input.address).fetchWithPay;

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
