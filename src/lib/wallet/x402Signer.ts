"use client";

import algosdk from "algosdk";
import type { ClientAvmSigner } from "@x402/avm";
import { ensurePeraSession } from "./pera";

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
      const pera = await ensurePeraSession();
      const decoded = txns.map((t) => algosdk.decodeUnsignedTransaction(t));
      // Determine which transactions this wallet should sign:
      // Default to transactions where txn.sender matches address, or explicitly indexesToSign.
      const toSign = indexesToSign ?? decoded
        .map((txn, i) => (txn.sender.toString() === address ? i : -1))
        .filter((i) => i !== -1);

      // In ARC-0001 / Pera, unsigned transactions in an atomic group must have signers: []
      const signerTxns = decoded.map((txn, i) => ({
        txn,
        signers: toSign.includes(i) ? [address] : [],
      }));

      const signed = await pera.signTransaction([signerTxns]);

      // Pera filters out nulls and returns only the signed transactions for the toSign entries in order.
      const signedMap = new Map<number, Uint8Array>();
      toSign.forEach((txnIndex, k) => {
        if (signed && signed[k]) {
          signedMap.set(txnIndex, signed[k]);
        }
      });

      return txns.map((_, i) => signedMap.get(i) ?? null);
    },
  };
}
