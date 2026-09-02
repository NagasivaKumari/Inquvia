"use client";

import { useEffect, useState } from "react";
import {
  checkAssetOptIn,
  signAndSendUsdc,
  signAndSendUsdcOptIn,
} from "@/lib/wallet/pera";
import { API_BASE, ALGORAND_CONFIG } from "@/lib/config";
import { WalletBadge } from "./WalletBadge";
import styles from "./WalletConnector.module.css";

const NETWORK = ALGORAND_CONFIG.network;

interface PersistedWallet {
  address: string;
  network: string;
  connected: boolean;
}

export function WalletConnector() {
  const [wallet, setWallet] = useState<PersistedWallet | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState("");
  const [optedIn, setOptedIn] = useState(false);

  // Only the algod node is required - Pera connect needs no project id.
  const configured = !!ALGORAND_CONFIG.algodServer;

  useEffect(() => {
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((auth) => {
        if (auth.user?.walletAddress) {
          setWallet({
            address: auth.user.walletAddress,
            network: auth.user.walletNetwork ?? "Algorand",
            connected: true,
          });
        }
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const onConnected = async (address: string) => {
    setWallet({ address, network: NETWORK, connected: true });
    const opt = await checkAssetOptIn(address).catch(() => false);
    setOptedIn(opt);
  };

  const onDisconnected = () => {
    setWallet(null);
    setOptedIn(false);
  };

  const doOptIn = async () => {
    if (!wallet) return;
    setPaymentStatus("Requesting USDC opt-in…");
    setError("");
    try {
      const { txid } = await signAndSendUsdcOptIn(wallet.address);
      setPaymentStatus(`USDC opt-in submitted · tx ${txid.slice(0, 12)}…`);
      setOptedIn(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Opt-in failed");
    }
  };

  // ponytail: test payment = send 0.01 USDC to the connected address (self-transfer).
  // Real x402 settlement to facilitators can route here once a provider is chosen.
  const sendTestPayment = async () => {
    if (!wallet) return;
    setPaymentStatus("Signing USDC payment in Pera…");
    setError("");
    try {
      const { txid, assetId } = await signAndSendUsdc({
        from: wallet.address,
        to: wallet.address,
        amountMicroUsdc: 10000, // 0.01 USDC
      });
      setPaymentStatus(`USDC payment signed & sent · tx ${txid.slice(0, 12)}… (ASA ${assetId})`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    }
  };

  if (!loaded) {
    return <div className="text-sm text-muted">Loading wallet…</div>;
  }

  if (wallet?.connected) {
    return (
      <div className={styles.connected}>
        <div className={styles.connectedHeader}>
          <span className="badge badge-success">Connected</span>
          <WalletBadge
            address={wallet.address}
            onConnected={onConnected}
            onDisconnected={onDisconnected}
            compact
          />
        </div>
        <div className={styles.network}>{wallet.network}</div>

        <div className={styles.actions}>
          {!optedIn ? (
            <button onClick={doOptIn} className="btn btn-secondary btn-sm">
              Opt in to USDC (ASA {ALGORAND_CONFIG.usdcAsa})
            </button>
          ) : (
            <button onClick={sendTestPayment} className="btn btn-primary btn-sm">
              Sign & send 0.01 USDC
            </button>
          )}
        </div>
        {!configured && (
          <p className={styles.warn}>Configure ALGOD_SERVER (an Algorand node) to sign on {ALGORAND_CONFIG.network}.</p>
        )}
        {paymentStatus && <p className={styles.status}>{paymentStatus}</p>}
        {error && <p className={styles.error}>{error}</p>}
      </div>
    );
  }

  return (
    <div className={styles.wrapper}>
      <WalletBadge onConnected={onConnected} onDisconnected={onDisconnected} />
      {!configured && (
        <p className={styles.warn}>
          Real signing not configured — set ALGOD_SERVER (an Algorand node) in .env.
        </p>
      )}
    </div>
  );
}
