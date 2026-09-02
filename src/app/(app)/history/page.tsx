"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import type { Investigation } from "@/lib/types";
import { ASSESSMENT_LABELS, RISK_LABELS } from "@/lib/types";
import styles from "./page.module.css";

export default function HistoryPage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/investigations`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        setInvestigations(data.investigations ?? []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const filtered = investigations.filter(
    (inv) =>
      !filter ||
      inv.question.toLowerCase().includes(filter.toLowerCase()) ||
      inv.title.toLowerCase().includes(filter.toLowerCase())
  );

  if (loading) {
    return <p className="text-muted animate-pulse">Loading history…</p>;
  }

  if (investigations.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">📋</div>
        <h2 className="heading-md">No investigations yet</h2>
        <p>Your investigations will appear here.</p>
        <Link href="/investigate" className="btn btn-primary" style={{ marginTop: 16 }}>
          Start an Investigation
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className="heading-lg">Investigation History</h1>
        <input
          type="search"
          className="form-input"
          placeholder="Search investigations…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Search investigations"
          style={{ maxWidth: 320 }}
        />
      </header>

      <div className={styles.list}>
        {filtered.map((inv) => (
          <Link
            key={inv.id}
            href={`/investigation/${inv.id}`}
            className={`card card-interactive ${styles.item}`}
          >
            <div className={styles.itemMain}>
              <p className={styles.question}>&ldquo;{inv.question}&rdquo;</p>
              <div className={styles.meta}>
                <span className={`badge ${riskBadge(inv.risk)}`}>
                  {RISK_LABELS[inv.risk]} Risk
                </span>
                {inv.status === "completed" && (
                  <>
                    <span>{inv.confidence}% confidence</span>
                    <span>{inv.evidence.length} evidence sources</span>
                  </>
                )}
                <span>{formatDate(inv.createdAt)}</span>
              </div>
            </div>
            {inv.status === "completed" && (
              <span className={styles.conclusion}>
                {ASSESSMENT_LABELS[inv.conclusion]}
              </span>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}

function riskBadge(risk: Investigation["risk"]): string {
  const map = {
    low: "badge-success",
    moderate: "badge-warning",
    high: "badge-danger",
    unknown: "badge-neutral",
  };
  return map[risk];
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  if (diff < 86400000) return "Today";
  if (diff < 172800000) return "Yesterday";
  return d.toLocaleDateString();
}
