"use client";

import { useEffect, useState } from "react";
import { shortenAddress } from "@/lib/wallet";
import { connectPera, disconnectPera, getPera } from "@/lib/wallet/pera";
import { API_BASE, ALGORAND_CONFIG } from "@/lib/config";
import { apiFetch, invalidateAuthCache } from "@/lib/api";
import { WalletLogo } from "./WalletLogo";
import styles from "./WalletBadge.module.css";

interface WalletBadgeProps {
  /** injected when an upstream page already connected from elsewhere. */
  address?: string;
  onConnected?: (address: string) => void;
  onDisconnected?: () => void;
  compact?: boolean;
}

function base64(u8: Uint8Array): string {
  let bin = "";
  u8.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}

/**
 * Wallet identity control (Pera only):
 *  - not connected -> "Connect wallet" button
 *  - connected     -> shows ONLY the Pera logo; click it to reveal the address
 */
export function WalletBadge({ address, onConnected, onDisconnected, compact }: WalletBadgeProps) {
  const [connected, setConnected] = useState<string>(address ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setConnected(address ?? "");
  }, [address]);

  useEffect(() => {
    if (!address) {
      getPera()
        .reconnectSession()
        .then((accounts) => {
          if (accounts && accounts.length > 0) {
            setConnected(accounts[0]);
            onConnected?.(accounts[0]);
          }
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!connected) {
    const doConnect = async () => {
      setLoading(true);
      setError("");
      try {
        const w = await connectPera();
        const message = `Sign to verify control of ${w.address} in ${ALGORAND_CONFIG.network} at ${Date.now()}`;
        const { signChallenge } = await import("@/lib/wallet/pera");
        const { signature, authenticatorData } = await signChallenge(
          w.address,
          message,
          window.location.origin
        );

        const res = await apiFetch(`${API_BASE}/api/wallet/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            providerId: "pera",
            address: w.address,
            message,
            authenticatorData: base64(authenticatorData),
            signatureB64: base64(signature),
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Connection failed");

        invalidateAuthCache();
        setConnected(data.wallet.address);
        onConnected?.(data.wallet.address);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Connection failed");
      } finally {
        setLoading(false);
      }
    };

    return (
      <div className={styles.notConnected}>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={loading}
          onClick={doConnect}
        >
          {loading ? "Connecting…" : "Connect wallet"}
        </button>
        {error && <p className={styles.error}>{error}</p>}
      </div>
    );
  }

  const doDisconnect = async () => {
    setLoading(true);
    try {
      await apiFetch(`${API_BASE}/api/wallet/connect`, { method: "DELETE" }).catch(() => {});
      await disconnectPera().catch(() => {});
      invalidateAuthCache();
      setConnected("");
      onDisconnected?.();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={`${styles.connected} ${compact ? styles.compact : ""}`}>
      <div className={styles.info}>
        <WalletLogo id="pera" size={compact ? 20 : 26} />
        <span className={styles.network}>{ALGORAND_CONFIG.network}</span>
        <span className={styles.address} title={connected}>
          {shortenAddress(connected)}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={doDisconnect}
          disabled={loading}
          title="Disconnect wallet"
        >
          {loading ? "…" : "Disconnect"}
        </button>
      </div>
    </div>
  );
}