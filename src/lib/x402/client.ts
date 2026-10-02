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
 * Session-level cache: once we confirm a wallet is opted-in for this page
 * load, skip the server round-trip and Pera prompt on subsequent calls.
 */
const _optInCache = new Set<string>();

/**
 * Make sure the paying wallet is opted into USDC before the payment is built.
 * Opting-in is a self asset-transfer of 0, signed via Pera and broadcast
 * through the backend (browser-direct algod calls fail silently — the bug the
 * /api/x402 proxy endpoints exist to avoid).
 *
 * The result is cached per-address for the lifetime of the page so subsequent
 * investigations from the same wallet never re-prompt.
 */
async function ensureUsdcOptIn(address: string): Promise<void> {
  if (_optInCache.has(address)) return;   // already confirmed this session

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
    _optInCache.add(address);              // remember for this session
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
  _optInCache.add(address);                // successful opt-in, cache it
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
  "x-402-payment",
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

function toErrorMessage(body: Record<string, unknown> | null, status: number): string {
  if (body && typeof body.error === "string" && body.error) return body.error;
  const detail = body?.detail;
  if (detail && typeof detail === "object") {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === "string" && m) return m;
  }
  const details = body?.details && typeof body.details === "object" ? (body.details as Record<string, unknown>) : null;
  switch (status) {
    case 401:
      return "Please sign in to continue.";
    case 403:
      return "You do not have permission to perform this action.";
    case 413: {
      const max = typeof details?.maxSizeMB === "number" ? ` Maximum allowed size is ${details.maxSizeMB}MB.` : "";
      return `File is too large.${max}`;
    }
    case 415: {
      const accepted = Array.isArray(details?.acceptedFileExtensions) && details.acceptedFileExtensions.length
        ? ` Supported formats: ${details.acceptedFileExtensions.map((e) => String(e).replace(".", "").toUpperCase()).join(", ")}.`
        : "";
      return `File type not supported.${accepted}`;
    }
    case 400:
    case 422:
      return "Invalid request. Please check your input and try again.";
    case 402:
      return "Payment is required to complete this request.";
    default:
      return status >= 500
        ? "Something went wrong on the server. Please try again."
        : `The server returned an unexpected error.`;
  }
}

function withErrorMeta(err: Error, res: Response, body: Record<string, unknown> | null): Error {
  const meta = err as Error & { status?: number; code?: string };
  meta.status = res.status;
  const code = body && typeof body.errorCode === "string" ? body.errorCode : undefined;
  if (code) meta.code = code;
  return err;
}

interface StableFile {
  data: ArrayBuffer;
  name: string;
  type: string;
}

async function snapshotFiles(files: File[] | undefined): Promise<StableFile[]> {
  return Promise.all(
    (files ?? []).map(async (file) => ({
      data: await file.arrayBuffer(),
      name: file.name,
      type: file.type,
    }))
  );
}

function appendStableFiles(form: FormData, field: string, files: StableFile[]): void {
  for (const file of files) {
    form.append(field, new Blob([file.data], { type: file.type }), file.name);
  }
}

function paymentEndpoint(endpoint: string): string {
  if (endpoint.startsWith("http")) return endpoint;
  return `${API_BASE}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;
}

interface PaidPostInput {
  address: string;
  endpoint: string;
  files?: File[];
  idempotencyKey?: string;
  signal?: AbortSignal;
  buildBody: (files: StableFile[]) => { headers: Record<string, string>; body: BodyInit };
}

async function postPaid(input: PaidPostInput): Promise<Response> {
  const stableFiles = await snapshotFiles(input.files);
  const hasFiles = stableFiles.length > 0;
  const capabilityId = input.endpoint.split("/").filter(Boolean).pop();
  const { fetchWithPay, httpClient } = buildX402Payment(input.address, capabilityId);
  const endpointUrl = paymentEndpoint(input.endpoint);
  const requestHeadersFor = (extra: HeadersInit) => {
    const headers = new Headers(extra);
    if (input.idempotencyKey) headers.set("Idempotency-Key", input.idempotencyKey);
    return headers;
  };
  const call = (f: typeof fetchWithPay, extraHeaders: Record<string, string>) => {
    const body = input.buildBody(stableFiles);
    return f(endpointUrl, {
      method: "POST",
      headers: requestHeadersFor({ ...body.headers, ...extraHeaders }),
      body: body.body,
      signal: input.signal,
    });
  };

  await ensureUsdcOptIn(input.address);

  let res: Response;
  if (hasFiles) {
    // ── File-upload path ──
    // Files can't be replayed by the x402 wrapper, so we do the 402 dance
    // manually: probe → sign once → send the paid request.  No retries that
    // would trigger a second Pera signing prompt.
    emitPay("gate-rejected", { message: "Probing endpoint for payment requirements…" });
    res = await call(apiFetch as typeof fetchWithPay, {});
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
      res = await call(
        apiFetch as typeof fetchWithPay,
        httpClient.encodePaymentSignatureHeader(payload)
      );
      // Record the settlement result but do NOT retry on `recovered` —
      // `recovered` only means the library reconciled the payment state,
      // not that a fresh transaction is needed. Retrying here was causing
      // a second Pera signing prompt.
      await httpClient
        .processPaymentResult(payload, (name) => res.headers.get(name), res.status)
        .catch(() => { /* settlement bookkeeping is best-effort */ });
    }
  } else {
    // ── JSON / URL-only path ──
    // `fetchWithPay` already handles the 402 → sign → retry cycle internally.
    // Do NOT catch + rebuild a fresh x402 payment — that was causing a second
    // Pera signing prompt on every transient error.
    res = await call(fetchWithPay, {});
  }
  return res;
}

async function throwResponseError(res: Response): Promise<never> {
  const required = res.headers.get("PAYMENT-REQUIRED") || res.headers.get("payment-required");
  if (required) {
    try {
      const decoded = JSON.parse(atob(required)) as { error?: string };
      const reason = decoded.error ? `: ${decoded.error}` : "";
      throw new Error(`Payment required${reason}`);
    } catch (err) {
      if (err instanceof Error && err.message.startsWith("Payment required")) throw err;
    }
  }
  const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  throw withErrorMeta(new Error(toErrorMessage(body, res.status)), res, body);
}

export interface PaidEvidenceResult {
  data: unknown;
  status: string;
  txId: string;
}

export async function payForCapability(input: {
  address: string;
  endpoint: string;
  question: string;
  serviceName?: string;
  text?: string;
  url?: string;
  files?: File[];
  idempotencyKey?: string;
  reinvestigateFrom?: string;
  signal?: AbortSignal;
}): Promise<PaidInvestigationResult> {
  const res = await postPaid({
    address: input.address,
    endpoint: input.endpoint,
    files: input.files,
    idempotencyKey: input.idempotencyKey,
    signal: input.signal,
    buildBody: (files) => {
      if (files.length) {
        const form = new FormData();
        form.append("question", input.question);
        if (input.text) form.append("text", input.text);
        if (input.url) form.append("url", input.url);
        if (input.serviceName) form.append("serviceName", input.serviceName);
        if (input.reinvestigateFrom) form.append("reinvestigateFrom", input.reinvestigateFrom);
        appendStableFiles(form, "files", files);
        return { headers: {} as Record<string, string>, body: form };
      }
      return {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: input.question,
          serviceName: input.serviceName,
          text: input.text,
          url: input.url,
          reinvestigateFrom: input.reinvestigateFrom,
        }),
      };
    },
  });

  if (!res.ok) await throwResponseError(res);
  const txId = extractSettlementTxId(res);
  const body = (await res.json().catch(() => ({}))) as {
    id?: string;
    status?: string;
    capability?: string;
  };
  if (!body.id) throw new Error("Investigation did not return an id");
  return {
    id: body.id,
    status: body.status ?? "",
    txId,
    capability: body.capability,
  };
}

export async function payForEvidence(input: {
  address: string;
  endpoint: string;
  fields?: Record<string, string>;
  json?: unknown;
  files?: File[];
  fileField?: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
}): Promise<PaidEvidenceResult> {
  const res = await postPaid({
    address: input.address,
    endpoint: input.endpoint,
    files: input.files,
    idempotencyKey: input.idempotencyKey,
    signal: input.signal,
    buildBody: (files) => {
      if (files.length) {
        const form = new FormData();
        for (const [name, value] of Object.entries(input.fields ?? {})) form.append(name, value);
        appendStableFiles(form, input.fileField ?? "file", files);
        return { headers: {} as Record<string, string>, body: form };
      }
      return {
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input.json ?? input.fields ?? {}),
      };
    },
  });

  if (!res.ok) await throwResponseError(res);
  const txId = extractSettlementTxId(res);
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  const status =
    data && typeof data === "object" && "status" in data
      ? String((data as { status?: unknown }).status ?? "")
      : "";
  return { data, status, txId };
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
    const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    throw withErrorMeta(new Error(toErrorMessage(body, res.status)), res, body);
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

export function normalizeCapabilityEndpoint(value: string): string {
  const raw = value.trim();
  if (!raw) return "";
  if (raw.startsWith("/api/evidence/") || raw.startsWith("/api/x402/")) return raw;
  if (raw.startsWith("evidence-")) return `/api/evidence/${raw.replace(/^evidence-/, "")}`;
  if (["contradictions", "duplicates", "timeline", "gaps", "assess", "authenticity"].includes(raw)) {
    return `/api/evidence/${raw}`;
  }
  return `/api/x402/${raw.replace(/^\/+/, "")}`;
}

/** Determine the correct atomic endpoint for a set of inputs. */
export function detectCapabilityEndpoint(files: File[], url: string): string {
  const mimes = files.map((f) => f.type.toLowerCase());
  const names = files.map((f) => f.name.toLowerCase());
  const urlList = url ? url.split(/[\n,]+/).map((u) => u.trim()).filter(Boolean) : [];

  if (files.length >= 2 || urlList.length >= 2) {
    const imageExts = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"];
    if (mimes.some((m) => m.startsWith("image/")) || names.some((n) => imageExts.some((ext) => n.endsWith(ext)))) {
      return "/api/x402/image-batch-investigation";
    }
    return "/api/evidence/contradictions";
  }

  // Images
  const imageExts = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"];
  if (
    mimes.some((m) => m.startsWith("image/")) ||
    names.some((n) => imageExts.some((ext) => n.endsWith(ext)))
  ) {
    return files.length >= 2 ? "/api/x402/image-batch-investigation" : "/api/x402/image-investigation";
  }

  // Videos
  const videoExts = [".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".wmv"];
  if (
    mimes.some((m) => m.startsWith("video/") || m === "video/quicktime") ||
    names.some((n) => videoExts.some((ext) => n.endsWith(ext)))
  ) {
    return "/api/x402/video-investigation";
  }

  // Audio
  const audioExts = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"];
  if (
    mimes.some((m) => m.startsWith("audio/")) ||
    names.some((n) => audioExts.some((ext) => n.endsWith(ext)))
  ) {
    return "/api/x402/audio-investigation";
  }

  // Structured Data
  const dataExts = [".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls", ".parquet"];
  if (
    mimes.some((m) => m.includes("json") || m.includes("csv") || m.includes("excel") || m.includes("spreadsheet") || m.includes("parquet")) ||
    names.some((n) => dataExts.some((ext) => n.endsWith(ext)))
  ) {
    return "/api/x402/data-investigation";
  }

  // Documents
  const docExts = [".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt", ".html", ".htm", ".xhtml"];
  if (
    mimes.some((m) => m === "application/pdf" || m.includes("word") || m.includes("document") || m.includes("opendocument") || m.startsWith("text/")) ||
    names.some((n) => docExts.some((ext) => n.endsWith(ext)))
  ) {
    return "/api/x402/document-investigation";
  }

  if (url?.trim()) return "/api/x402/source-investigation";
  return "/api/x402/claim-investigation";
}
