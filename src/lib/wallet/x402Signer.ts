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
export function createX402Signer(address: string, capabilityId?: string): ClientAvmSigner {
  const emit = (step: string, extra?: Record<string, unknown>) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("inquvia:pay-diagnostic", { detail: { step, ...extra } })
      );
    }
  };
  const withDeadline = <T,>(
    promise: Promise<T>,
    ms: number,
    message: string
  ): Promise<T> =>
    Promise.race([
      promise,
      new Promise<T>((_, reject) =>
        setTimeout(() => reject(new Error(message)), ms)
      ),
    ]);
  return {
    address,
    async signTransactions(txns, indexesToSign) {
      try {
        const isVideo = capabilityId === "video-investigation";
        if (isVideo) console.log("x402Signer: signTransactions started (Video mode)");
        
        emit("preparing-session", { address });
        const pera = await ensurePeraSession();
        
        if (isVideo) console.log("x402Signer: session ready");
        emit("session-ready", { connected: pera.isConnected });
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

        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("inquvia:wallet-signing"));
        }
        emit("requesting-approval", { txCount: signerTxns.length });
        
        if (isVideo) console.log("x402Signer: calling pera.signTransaction");
        emit("pera-signing-start");
        const signed = await withDeadline(
          pera.signTransaction([signerTxns]),
          120000,
          "Signing timed out — please open the Pera Wallet app on your device, approve the request, or disconnect and reconnect your wallet."
        );
        if (isVideo) console.log("x402Signer: pera.signTransaction returned");
        emit("pera-signing-success");
        emit("request-approved");

        // Pera filters out nulls and returns only the signed transactions for the toSign entries in order.
        const signedMap = new Map<number, Uint8Array>();
        toSign.forEach((txnIndex, k) => {
          if (signed && signed[k]) {
            signedMap.set(txnIndex, signed[k]);
          }
        });

        return txns.map((_, i) => signedMap.get(i) ?? null);
      } catch (err) {
        console.error("x402Signer: error", err);
        const message = err instanceof Error ? err.message : String(err);
        emit("error", { message });
        if (/timed out/i.test(message)) {
          // If the signing request timed out, the WalletConnect bridge is likely dead or desynced.
          // Disconnect so the user can establish a fresh session on their next retry.
          try {
            const { disconnectPera } = await import("./pera");
            await disconnectPera();
          } catch {
            // best-effort cleanup
          }
        }
        throw err;
      }
    },
  };
}
