"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import type {
  EvidenceAcquisition,
  Investigation,
  ActivityEvent,
} from "@/lib/types";
import styles from "./page.module.css";

interface AuditRow {
  key: string;
  investigationId: string;
  investigationTitle: string;
  serviceName?: string;
  capability: string;
  amountMicro: number;
  network: string;
  txId?: string;
  status: string;
  updatedAt: string;
  blockReason?: string;
  capabilityPriceUsdc?: number;
  economicSummaryTotalSpend?: number;
}

const STATE_LABEL: Record<string, string> = {
  payment_required: "Payment required",
  awaiting_wallet: "Awaiting wallet",
  wallet_authorized: "Wallet authorized",
  payment_submitted: "Payment submitted",
  settling: "Settling",
  settled: "Settlement confirmed",
  evidence_requested: "Evidence requested",
  evidence_received: "Evidence received",
  wallet_rejected: "Wallet rejected",
  insufficient_balance: "Insufficient balance",
  unsupported_network: "Unsupported network",
  payment_failed: "Payment failed",
  settlement_failed: "Settlement failed",
  provider_unavailable: "Provider unavailable",
  evidence_request_failed: "Evidence request failed",
};

function microToUsdc(micro: number): string {
  return ((micro ?? 0) / 1e6).toFixed(4);
}

export default function ActivityPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/investigations`)
      .then((r) => r.json())
      .then((data: { investigations?: Investigation[] }) => {
        const investigations = data.investigations ?? [];
        const audit: AuditRow[] = [];
        const allEvents: ActivityEvent[] = [];
        for (const inv of investigations) {
          for (const acq of inv.acquisitions ?? []) {
            audit.push(toRow(inv, acq));
          }
          allEvents.push(...(inv.activity ?? []));
        }
        setInvestigations(investigations);
        setRows(
          audit.sort(
            (a, b) =>
              new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
          )
        );
        setEvents(
          allEvents.sort(
            (a, b) =>
              new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
          )
        );
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-muted animate-pulse">Loading activity…</p>;
  }

  if (rows.length === 0 && events.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">📡</div>
        <h2 className="heading-md">No activity yet</h2>
        <p>x402 evidence acquisition activity will appear here after your first investigation.</p>
        <Link href="/investigate" className="btn btn-primary" style={{ marginTop: 16 }}>
          Start an Investigation
        </Link>
      </div>
    );
  }

  const totalSpendMicro = investigations.reduce((s: number, inv: Investigation) => {
    const ecoSpend = Number(inv.economicSummary?.totalSpend);
    const spend = Number.isFinite(ecoSpend) && ecoSpend > 0
      ? ecoSpend
      : (inv.capabilityPriceUsdc ?? 0);
    return s + Math.round(spend * 1e6);
  }, 0);
  const gateways = new Set(rows.map((r) => r.serviceName).filter(Boolean));

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className="heading-lg">Economic Activity</h1>
        <p className="text-muted">
          Audit trail of evidence purchases and x402 settlements.
        </p>
      </header>

      <div className={styles.summary}>
        <div className={`card ${styles.summaryCard}`}>
          <span className={styles.summaryLabel}>User payment</span>
          <span className={styles.summaryValue}>
            ${microToUsdc(totalSpendMicro)} USDC
          </span>
        </div>
        <div className={`card ${styles.summaryCard}`}>
          <span className={styles.summaryLabel}>Evidence checks performed</span>
          <span className={styles.summaryValue}>{rows.length}</span>
        </div>
        <div className={`card ${styles.summaryCard}`}>
          <span className={styles.summaryLabel}>Services</span>
          <span className={styles.summaryValue}>{gateways.size}</span>
        </div>
        <div className={`card ${styles.summaryCard}`}>
          <span className={styles.summaryLabel}>Network</span>
          <span className={styles.summaryValue}>Algorand</span>
        </div>
      </div>

      <div className={styles.list}>
        {rows.map((p) => {
          const isSettled = p.status === "evidence_received" || p.status === "settled";
          return (
            <div key={p.key} className={`card ${styles.item}`}>
              <div className={styles.itemHeader}>
                <div>
                  <Link
                    href={`/investigation/${p.investigationId}`}
                    className={styles.invLink}
                  >
                    {p.investigationTitle || p.investigationId}
                  </Link>
                  <p className={styles.capability}>
                    {p.serviceName ?? "No service"} ·{" "}
                    {formatCapability(p.capability)}
                  </p>
                </div>
<div className={styles.amount}>
              <span className={styles.amountValue}>
                {p.txId
                  ? `${microToUsdc(p.amountMicro)} USDC`
                  : "internal check — included in user payment"}
              </span>
              <span
                className={`badge ${isSettled ? "badge-success" : p.blockReason ? "badge-danger" : "badge-info"}`}
              >
                {STATE_LABEL[p.status] ?? p.status.replaceAll("_", " ")}
              </span>
            </div>
              </div>
              <div className={styles.details}>
                <span>Network: {p.network}</span>
                <span>Protocol: x402</span>
                <span>{new Date(p.updatedAt).toLocaleString()}</span>
                {p.txId && <span className={styles.ref}>Tx: {p.txId}</span>}
              </div>
              {p.blockReason && (
                <p className={styles.blockReason}>{p.blockReason}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const toRow = (inv: Investigation, acq: EvidenceAcquisition): AuditRow => {
  return {
    key: acq.id,
    investigationId: inv.id,
    investigationTitle: inv.title,
    serviceName: acq.serviceName,
    capability: acq.capability,
    amountMicro: acq.amountMicro ?? 0,
    network: acq.network,
    txId: acq.txId,
    status: acq.paymentState,
    updatedAt: acq.updatedAt,
    blockReason: acq.blockReason,
    capabilityPriceUsdc: inv.capabilityPriceUsdc,
    economicSummaryTotalSpend: inv.economicSummary?.totalSpend,
  };
};

function formatCapability(cap: string): string {
  return cap.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}