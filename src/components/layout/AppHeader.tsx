"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE, ALGORAND_CONFIG } from "@/lib/config";
import { apiFetch, invalidateAuthCache } from "@/lib/api";
import { shortenAddress } from "@/lib/wallet";
import { connectPera } from "@/lib/wallet/pera";
import styles from "./AppHeader.module.css";

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/investigate": "New investigation",
  "/investigate/launch": "Launch investigation",
  "/history": "Investigation history",
  "/reports": "Reports",
  "/activity": "Payment activity",
  "/settings": "Settings",
};

export function AppHeader({ onMenu }: { onMenu?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{
    name: string;
    email: string;
    walletAddress?: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => setUser(d.user ?? null))
      .catch(() => {});
  }, [pathname]);

  const title =
    TITLES[pathname] ??
    (pathname.startsWith("/investigation/")
      ? "Investigation"
      : pathname.startsWith("/reports/")
        ? "Report"
        : "Workspace");

  const connectWallet = async () => {
    setBusy(true);
    setError("");
    try {
      const { address } = await connectPera();
      const message = `Sign to verify control of ${address} in ${ALGORAND_CONFIG.network} at ${Date.now()}`;
      const { signChallenge } = await import("@/lib/wallet/pera");
      const { signature } = await signChallenge(address, message);
      let bin = "";
      signature.forEach((b) => (bin += String.fromCharCode(b)));
      const res = await apiFetch(`${API_BASE}/api/wallet/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          providerId: "pera",
          address,
          message,
          signatureB64: btoa(bin),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Connection failed");
      setUser((u) =>
        u
          ? { ...u, walletAddress: data.wallet.address }
          : { name: "", email: "", walletAddress: data.wallet.address }
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wallet connection failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className={styles.bar}>
      <div className={styles.left}>
        <button
          type="button"
          className={styles.menuBtn}
          onClick={onMenu}
          aria-label="Open workspace navigation"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>
        <div>
          <p className={styles.crumb}>Workspace / {ALGORAND_CONFIG.network}</p>
          <h1 className={styles.title}>{title}</h1>
        </div>
      </div>
      <div className={styles.right}>
        {error && <span className={styles.err}>{error}</span>}
        {user?.walletAddress ? (
          <span className={styles.wallet} title={user.walletAddress}>
            <span className={styles.walletDot} aria-hidden="true" />
            {shortenAddress(user.walletAddress)}
          </span>
        ) : (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={connectWallet}
            disabled={busy}
          >
            {busy ? "Connecting…" : "Connect wallet"}
          </button>
        )}
        {user ? (
          <div className={styles.userChip}>
            <span className={styles.userAvatar} aria-hidden="true">
              {user.name?.charAt(0)?.toUpperCase() ?? "U"}
            </span>
            <span className={styles.user}>{user.name}</span>
          </div>
        ) : (
          <Link href="/login" className="btn btn-primary btn-sm">
            Log in
          </Link>
        )}
        {user && (
          <button
            type="button"
            className={styles.logout}
            onClick={async () => {
              localStorage.removeItem("token");
              invalidateAuthCache();
              await apiFetch(`${API_BASE}/api/auth/logout`, { method: "POST" });
              router.push("/");
              router.refresh();
            }}
            aria-label="Sign out"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
          </button>
        )}
      </div>
    </header>
  );
}
