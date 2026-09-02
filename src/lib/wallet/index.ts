import type { WalletProviderInfo } from "../types";

/** Supported Algorand wallet providers. Modular: add new entries here. */
const WALLET_PROVIDERS: WalletProviderInfo[] = [
  { id: "pera", name: "Pera Algo Wallet", icon: "P", url: "https://perawallet.app" },
  { id: "defly", name: "Defly Wallet", icon: "D", url: "https://defly.app" },
];

export function getSupportedWallets(): WalletProviderInfo[] {
  return WALLET_PROVIDERS;
}

/** Shorten an Algorand address for display: ABCDE...WXYZ. */
export function shortenAddress(address: string, keep = 4): string {
  if (!address || address.length <= keep * 2) return address;
  return `${address.slice(0, keep)}…${address.slice(-keep)}`;
}

export interface WalletConnectionResult {
  address: string;
  network: string;
  providerId: string;
}

/**
 * Real wallet connection happens CLIENT-SIDE via the Pera SDK (src/lib/wallet/pera.ts),
 * which signs a challenge that the server verifies in /api/wallet/connect.
 * This server lib holds no private keys — only public address handling.
 */

export interface SpendingCheck {
  allowed: boolean;
  reason?: "per_evidence" | "per_investigation" | "session_budget" | "total_budget";
  limit: number;
  currentlySpent: number;
  remaining: number;
  requested: number;
}

/** Build amounts given user payment prefs and already-spent totals. */
export function canSpend(input: {
  requested: number;
  maxPerEvidenceCheck: number;
  perInvestigationRemaining: number;
  sessionRemaining: number;
  totalRemaining: number;
}): SpendingCheck {
  if (input.requested > input.maxPerEvidenceCheck) {
    return {
      allowed: false,
      reason: "per_evidence",
      limit: input.maxPerEvidenceCheck,
      currentlySpent: 0,
      remaining: 0,
      requested: input.requested,
    };
  }
  if (input.requested > input.perInvestigationRemaining) {
    return {
      allowed: false,
      reason: "per_investigation",
      limit: input.perInvestigationRemaining,
      currentlySpent: 0,
      remaining: input.perInvestigationRemaining,
      requested: input.requested,
    };
  }
  if (input.requested > input.sessionRemaining) {
    return {
      allowed: false,
      reason: "session_budget",
      limit: input.sessionRemaining,
      currentlySpent: 0,
      remaining: input.sessionRemaining,
      requested: input.requested,
    };
  }
  if (input.requested > input.totalRemaining) {
    return {
      allowed: false,
      reason: "total_budget",
      limit: input.totalRemaining,
      currentlySpent: 0,
      remaining: input.totalRemaining,
      requested: input.requested,
    };
  }
  return {
    allowed: true,
    requested: input.requested,
    limit: input.maxPerEvidenceCheck,
    currentlySpent: 0,
    remaining: input.requested,
  };
}

/** Expose for tests / settings page. */
export function walletProviderList(): WalletProviderInfo[] {
  return WALLET_PROVIDERS;
}
