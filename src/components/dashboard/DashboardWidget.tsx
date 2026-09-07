"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import type { Investigation } from "@/lib/types";
import styles from "./Dashboard.module.css";

interface DashboardData {
  totalInvestigations: number;
  investigationsThisWeek: number;
  evidenceChecksPurchased: number;
  totalSpend: number;
  averageConfidence: number;
  recentInvestigations: Investigation[];
}

export function DashboardWidget() {
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/dashboard`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, []);

  if (!data || data.totalInvestigations === 0) return null;

  return (
    <section className={styles.dashboard} aria-labelledby="dashboard-heading">
      <h2 id="dashboard-heading" className="heading-md">
        Your investigations
      </h2>
      <div className={styles.stats}>
        <div className={`card ${styles.stat}`}>
          <span className={styles.statValue}>{data.totalInvestigations}</span>
          <span className={styles.statLabel}>Total investigations</span>
        </div>
        <div className={`card ${styles.stat}`}>
          <span className={styles.statValue}>{data.investigationsThisWeek}</span>
          <span className={styles.statLabel}>This week</span>
        </div>
        <div className={`card ${styles.stat}`}>
          <span className={styles.statValue}>{data.evidenceChecksPurchased}</span>
          <span className={styles.statLabel}>Evidence checks</span>
        </div>
        <div className={`card ${styles.stat}`}>
          <span className={styles.statValue}>
            ${(data.totalSpend ?? 0).toFixed(3)}
          </span>
          <span className={styles.statLabel}>Total spend</span>
        </div>
        <div className={`card ${styles.stat}`}>
          <span className={styles.statValue}>
            {Math.round(data.averageConfidence ?? 0)}%
          </span>
          <span className={styles.statLabel}>Avg confidence</span>
        </div>
      </div>
      {data.recentInvestigations?.length > 0 && (
        <div className={styles.recent}>
          <h3 className="heading-sm text-muted">Recent</h3>
          {data.recentInvestigations.slice(0, 3).map((inv) => (
            <Link
              key={inv.id}
              href={`/investigation/${inv.id}`}
              className={styles.recentItem}
            >
              {inv.question}
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
