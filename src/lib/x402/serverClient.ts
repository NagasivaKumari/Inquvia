import { x402Client, wrapFetchWithPayment, decodePaymentResponseHeader } from "@x402/fetch";
import { ExactAvmScheme } from "@x402/avm/exact/client";
import { ALGORAND_NETWORK_CAIP2 } from "../config";
import { createServerSigner } from "../wallet/serverSigner";

/**
 * Server-side downstream x402 acquisition. Inquvia's backend signs + settles
 * the payment to an evidence service from Inquvia's own wallet (not the
 * client's browser). No "use client" — safe to import from route handlers.
 */
export async function acquireEvidenceServerSide(opts: {
  endpoint: string;
  question: string;
  capability: string;
}): Promise<{ txId: string; evidence: unknown }> {
  const signer = createServerSigner();
  if (!signer) {
    throw new Error("Server wallet not configured (SERVER_WALLET_MNEMONIC)");
  }
  const scheme = new ExactAvmScheme(signer);
  const client = new x402Client().register(ALGORAND_NETWORK_CAIP2, scheme);
  const fetchWithPay = wrapFetchWithPayment(fetch, client);

  const res = await fetchWithPay(opts.endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question: opts.question,
      capability: opts.capability,
      from: signer.address,
    }),
  });

  if (!res.ok) {
    throw new Error(`Evidence service returned ${res.status}`);
  }

  const txId = extractSettlementTxId(res);
  const evidence = await res.json().catch(() => null);
  return { txId, evidence };
}

const SETTLEMENT_HEADER_NAMES = [
  "x-payment-response",
  "x-x402-payment",
  "x-payment",
];

function extractSettlementTxId(res: Response): string {
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
      // keep scanning
    }
  }
  return "";
}
