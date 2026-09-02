"use client";

import { useEffect, useState } from "react";
import type { PaymentRecord } from "@/lib/types";
import { API_BASE, ALGORAND_CONFIG } from "@/lib/config";
import styles from "./PaymentPanel.module.css";

interface Props {
  payments: PaymentRecord[];
}

export function PaymentPanel({ payments }: Props) {
  const [budget, setBudget] = useState<{
    spent: number;
    total: number;
    remaining: number;
  } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/user`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (d.budget) setBudget(d.budget);
      })
      .catch(() => {});
  }, []);

  const spent = payments
    .filter((p) => p.status === "settled")
    .reduce((s, p) => s + p.amount, 0);

  if (payments.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="payment-heading">
      <h2 id="payment-heading" className="heading-md">
        Evidence purchases
      </h2>
      <p className="text-sm text-muted">
        Transparent payment activity for evidence acquisition.
      </p>

      <div className={styles.liveBanner}>
        <strong>LIVE — {ALGORAND_CONFIG.network}</strong> — real USDC will be
        spent on these evidence checks.
      </div>

      {budget && (
        <div className={`card ${styles.budgetCard}`}>
          <div className={styles.budgetRow}>
            <span>
              Budget <strong>${budget.total.toFixed(2)} USDC</strong>
            </span>
            <span>
              Spent <strong>${spent.toFixed(3)}</strong>
            </span>
            <span>
              Remaining{" "}
              <strong>${Math.max(0, budget.total - spent).toFixed(3)}</strong>
            </span>
          </div>
        </div>
      )}

      <div className={styles.list}>
        {payments.map((p) => (
          <div key={p.id} className={`card ${styles.card}`}>
            <div className={styles.header}>
              <span className={styles.capability}>
                {formatCapability(p.capability)}
              </span>
              <span className={styles.amount}>
                ${p.amount.toFixed(3)} {p.currency}
              </span>
            </div>
            <div className={styles.details}>
              <div>
                <span className={styles.label}>Payment</span>
                <span>
                  {p.status === "settled" ? "✓ " : ""}
                  {capitalize(p.status)}
                </span>
              </div>
              <div>
                <span className={styles.label}>Network</span>
                <span>{p.network}</span>
              </div>
              <div>
                <span className={styles.label}>Protocol</span>
                <span>{p.protocol}</span>
              </div>
              {p.settlementRef && (
                <div>
                  <span className={styles.label}>Reference</span>
                  <span className={styles.ref}>{p.settlementRef}</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function formatCapability(cap: string): string {
  return cap.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
