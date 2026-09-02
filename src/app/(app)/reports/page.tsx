"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import type { Investigation } from "@/lib/types";
import { ASSESSMENT_LABELS } from "@/lib/types";
import styles from "./page.module.css";

export default function ReportsPage() {
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/investigations`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        const completed = (data.investigations ?? []).filter(
          (i: Investigation) => i.status === "completed"
        );
        setInvestigations(completed);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-muted animate-pulse">Loading reports…</p>;
  }

  if (investigations.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" aria-hidden="true">📄</div>
        <h2 className="heading-md">No reports yet</h2>
        <p>Completed investigations can be saved as reports.</p>
        <Link href="/investigate" className="btn btn-primary" style={{ marginTop: 16 }}>
          Start an Investigation
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className="heading-lg">Investigation Reports</h1>
        <p className="text-muted">
          Evidence-backed reports from completed investigations.
        </p>
      </header>

      <div className={styles.grid}>
        {investigations.map((inv) => (
          <Link
            key={inv.id}
            href={`/reports/${inv.id}`}
            className={`card card-interactive ${styles.card}`}
          >
            <h2 className="heading-sm">{inv.title}</h2>
            <p className={styles.question}>&ldquo;{inv.question}&rdquo;</p>
            <div className={styles.footer}>
              <span>{ASSESSMENT_LABELS[inv.conclusion]}</span>
              <span>{inv.confidence}% confidence</span>
              <span>{new Date(inv.createdAt).toLocaleDateString()}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
