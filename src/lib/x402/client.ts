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

  override async createPaymentPayload(
    x402Version: number,
    requirements: PaymentRequirements
  ): Promise<PaymentPayloadResult> {
    const { amount, asset, payTo, extra } = requirements;
    const feePayer = (extra?.feePayer ?? undefined) as string | undefined;
    const algod = new algosdk.Algodv2(
      ALGORAND_CONFIG.algodToken,
      ALGORAND_CONFIG.algodServer,
      ALGORAND_CONFIG.algodPort
    );
    const sp = await algod.getTransactionParams().do();
    const feePerByte = Number(sp.fee);
    const minFee = Number(sp.minFee);
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
        suggestedParams: { ...sp, fee: Number(fee), flatFee: flat },
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
          suggestedParams: { ...sp, fee: Number(fee), flatFee: true },
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

  const endpointUrl = input.endpoint.startsWith("http")
    ? input.endpoint
    : `${API_BASE}${input.endpoint.startsWith("/") ? "" : "/"}${input.endpoint}`;

  const res = await fetchWithPay(endpointUrl, {
    method: "POST",
    headers: requestHeaders,
    body,
    signal: input.signal,
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
  if (mimes.some((m) => m.startsWith("audio/"))) return "/api/x402/audio-investigation";
  if (url?.trim()) return "/api/x402/source-investigation";
  return "/api/x402/claim-investigation";
}
