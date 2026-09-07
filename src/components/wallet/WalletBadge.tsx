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
  const [showInfo, setShowInfo] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (address) setConnected(address);
    // Eagerly reconnect Pera session if a previous session exists in localStorage
    getPera()
      .reconnectSession()
      .then((accounts) => {
        if (accounts && accounts.length > 0) {
          setConnected(accounts[0]);
          onConnected?.(accounts[0]);
        }
      })
      .catch(() => {});
  }, [address]);

  if (!connected) {
    const doConnect = async () => {
      setLoading(true);
      setError("");
      try {
        const w = await connectPera();
        const message = `Sign to verify control of ${w.address} in ${ALGORAND_CONFIG.network} at ${Date.now()}`;
        const { signChallenge } = await import("@/lib/wallet/pera");
        const { signature } = await signChallenge(w.address, message);

        const res = await apiFetch(`${API_BASE}/api/wallet/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            providerId: "pera",
            address: w.address,
            message,
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
    await apiFetch(`${API_BASE}/api/wallet/connect`, { method: "DELETE" }).catch(() => {});
    await disconnectPera().catch(() => {});
    invalidateAuthCache();
    setConnected("");
    setShowInfo(false);
    onDisconnected?.();
  };

  return (
    <div className={`${styles.connected} ${compact ? styles.compact : ""}`}>
      <button
        type="button"
        className={styles.logoButton}
        onClick={() => setShowInfo((s) => !s)}
        title="Connected wallet — click for address"
        aria-expanded={showInfo}
      >
        <WalletLogo id="pera" size={compact ? 26 : 34} />
      </button>

      {showInfo && (
        <div className={styles.info}>
          <span className={styles.network}>Pera · {ALGORAND_CONFIG.network}</span>
          <span className={styles.address}>{shortenAddress(connected)}</span>
          <button type="button" className="btn btn-ghost btn-xs" onClick={doDisconnect}>
            Disconnect
          </button>
        </div>
      )}
    </div>
  );
}