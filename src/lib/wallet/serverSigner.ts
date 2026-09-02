import algosdk from "algosdk";
import type { ClientAvmSigner } from "@x402/avm";
import { ORCHESTRATOR_CONFIG } from "../config";

/**
 * Server-side x402 signer backed by Inquvia's own wallet. Used to pay
 * downstream evidence services. Returns null when no server wallet mnemonic is
 * configured (downstream payments are then disabled -> evidence_unavailable).
 */
export function createServerSigner(): ClientAvmSigner | null {
  const mnemonic = ORCHESTRATOR_CONFIG.serverWalletMnemonic;
  if (!mnemonic) return null;
  const account = algosdk.mnemonicToSecretKey(mnemonic);
  return {
    address: account.addr.toString(),
    async signTransactions(txns, indexesToSign) {
      const toSign = indexesToSign ?? txns.map((_, i) => i);
      return txns.map((t, i) => {
        if (!toSign.includes(i)) return null;
        const decoded = algosdk.decodeUnsignedTransaction(t);
        return algosdk.signTransaction(decoded, account.sk).blob;
      });
    },
  };
}
