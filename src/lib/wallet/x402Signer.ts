"use client";

import algosdk from "algosdk";
import type { ClientAvmSigner } from "@x402/avm";
import { getPera } from "./pera";

/**
 * Bridges the Pera wallet to the x402 ClientAvmSigner interface.
 *
 * The x402 ExactAvmScheme builds an unsigned atomic group (ASA transfer for
 * the USDC payment) and asks the signer to sign the encoded transactions. We
 * decode them back to algosdk.Transaction objects, sign via Pera, and return
 * the signed bytes. Pera never shares private keys outside the wallet.
 */
export function createX402Signer(address: string): ClientAvmSigner {
  return {
    address,
    async signTransactions(txns, indexesToSign) {
      const decoded = txns.map((t) => algosdk.decodeUnsignedTransaction(t));
      const signed = await getPera().signTransaction([
        decoded.map((txn) => ({ txn, signers: [address] })),
      ]);
      const toSign = indexesToSign ?? decoded.map((_, i) => i);
      return txns.map((_, i) =>
        toSign.includes(i) ? (signed[i] ?? null) : null
      );
    },
  };
}
