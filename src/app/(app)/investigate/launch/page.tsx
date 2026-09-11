"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { payForCapability } from "@/lib/x402/client";
import { connectPera } from "@/lib/wallet/pera";
import { API_BASE, capabilityTitle } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import styles from "./page.module.css";

export default function LaunchPage() {
  return (
    <Suspense fallback={<p className="text-muted animate-pulse">Loading…</p>}>
      <LaunchContent />
    </Suspense>
  );
}

function LaunchContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const cap = searchParams.get("capability") ?? searchParams.get("cap") ?? "";

  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [walletAddress, setWalletAddress] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [price, setPrice] = useState<string | null>(null);

  // Resolve the atomic capability endpoint + its price. This is a review step:
  // nothing is charged until the user explicitly authorizes payment below.
  useEffect(() => {
    if (!q.trim()) {
      setError("No investigation prompt provided.");
      return;
    }
    if (cap) {
      setEndpoint(`/api/x402/${cap}`);
    } else {
      const hasUrl = /https?:\/\//i.test(q);
      const endpointDetected = hasUrl ? "/api/x402/source-investigation" : "/api/x402/claim-investigation";
      setEndpoint(endpointDetected);
    }
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => setWalletAddress(d.user?.walletAddress ?? ""))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, cap]);

  useEffect(() => {
    if (!endpoint) return;
    apiFetch(`${API_BASE}/api/investigate`)
      .then((r) => r.json())
      .then((d) => {
        const c = (d.capabilities ?? []).find(
          (x: { path: string }) => x.path === endpoint
        );
        if (c) setPrice(`$${c.priceUsdc} USDC`);
      })
      .catch(() => {});
  }, [endpoint]);

  useEffect(() => {
    const onWalletSigning = () => {
      setStatus("Approve the payment in the Pera app when prompted…");
    };
    const onDiagnostic = (e: Event) => {
      const d = (e as CustomEvent<{ step: string; message?: string }>)?.detail;
      const step = d?.step ?? "";
      const map: Record<string, string> = {
        "payment-params-ready": "Preparing network parameters…",
        "opt-in-required": "Your wallet isn't opted into USDC — approve the asset opt-in in Pera now…",
        "opt-in-ready": "USDC opt-in confirmed. Preparing payment…",
        "requesting-approval": "Approve the payment in the Pera app now…",
        "request-approved": "Payment approved.",
        "retrying-payment": "Payment attempt stalled — retrying once…",
      };
      if (map[step]) setStatus(map[step]);
    };
    window.addEventListener("inquvia:wallet-signing", onWalletSigning);
    window.addEventListener("inquvia:pay-diagnostic", onDiagnostic);
    return () => {
      window.removeEventListener("inquvia:wallet-signing", onWalletSigning);
      window.removeEventListener("inquvia:pay-diagnostic", onDiagnostic);
    };
  }, []);

  const connectAndPay = async () => {
    setError("");
    setStatus("Connecting wallet…");
    let address = walletAddress;
    if (!address) {
      try {
        const connected = await connectPera();
        address = connected.address;
        setWalletAddress(address);
      } catch (err) {
        console.error("[pay] connect error:", err);
        setError(err instanceof Error ? err.message : "Wallet connection failed");
        setStatus("");
        return;
      }
    }

    setStatus("Paying the selected capability & starting investigation…");
    try {
      const paid = await payForCapability({
        address,
        endpoint,
        question: q.trim(),
        idempotencyKey: crypto.randomUUID(),
      });
      router.replace(`/investigation/${paid.id}`);
    } catch (err) {
      console.error("[pay] payment error:", err);
      let detail = err instanceof Error ? err.message : "Payment failed";
      const any = err as { code?: string; reason?: string };
      if (any?.code) detail += ` (code: ${any.code})`;
      if (any?.reason) detail += ` (reason: ${any.reason})`;
      setError(detail);
      setStatus("");
    }
  };

  return (
    <div className={styles.page}>
      <h1 className="heading-md">Confirm investigation</h1>

      <div className={styles.summary}>
        <p className={styles.warn}>
          You are about to pay for a {capabilityTitle(endpoint)}
          {price ? ` (${price})` : ""} via x402 on Algorand. No charge happens
          until you authorize payment.
        </p>
      </div>

      <div className={styles.box}>
        <p className="text-muted">&ldquo;{q}&rdquo;</p>
      </div>

      {price && (
        <div className={styles.priceRow}>
          <span className="text-muted">Price</span>
          <strong>{price} USDC</strong>
        </div>
      )}

      <button className="btn btn-primary" onClick={connectAndPay} disabled={Boolean(status)}>
        {walletAddress ? "Authorize Payment & Start" : "Connect Pera Wallet & Pay"}
      </button>

      {status && !error && (
        <p className={`${styles.status} ${styles.animate}`}>
          {status} <span aria-hidden>…</span>
        </p>
      )}

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
    </div>
  );
}