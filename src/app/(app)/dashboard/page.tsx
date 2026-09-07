"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Investigation } from "@/lib/types";
import { API_BASE, APP_NAME, EXAMPLE_PROMPTS } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import styles from "./page.module.css";

interface DashboardData {
  totalInvestigations: number;
  investigationsThisWeek: number;
  evidenceChecksPurchased: number;
  totalSpend: number;
  averageConfidence: number;
  casesByType: Record<string, number>;
  recentInvestigations: Investigation[];
}

export default function DashboardPage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [user, setUser] = useState<{ name: string; walletAddress?: string; walletNetwork?: string } | null>(null);
  const [budget, setBudget] = useState<{ spent: number; total: number; remaining: number } | null>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch(`${API_BASE}/api/dashboard`).then((r) => r.json()),
      apiFetch(`${API_BASE}/api/auth/me`).then((r) => r.json()),
      apiFetch(`${API_BASE}/api/user`).then((r) => r.json()),
    ])
      .then(([d, me, b]) => {
        setData(d);
        setUser(me.user ?? null);
        setBudget(b.budget ?? null);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    router.push(`/investigate?q=${encodeURIComponent(question.trim())}`);
  };

  const firstName = user?.name?.split(" ")[0] ?? "there";
  const recent = data?.recentInvestigations ?? [];

  return (
    <div className={styles.page}>
      <div className={styles.greeting}>
        <p className={styles.eyebrow}>Your investigation workspace</p>
        <h1>Good {greet()}, {firstName}</h1>
        <p>Not sure? Let&apos;s check before you decide.</p>
      </div>

      <section className={styles.investBox}>
        <form onSubmit={submit} className={styles.investForm}>
          <label htmlFor="dashboard-question" className="sr-only">
            What do you want to investigate?
          </label>
          <textarea
            id="dashboard-question"
            className={styles.investInput}
            placeholder={`What would you like to check, ${firstName}?`}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
          />
          <div className={styles.investFooter}>
            <div className={styles.addRow}>
              <AddButton label="Image" cap="image-investigation" />
              <AddButton label="Video" cap="video-investigation" />
              <AddButton label="Document" cap="document-investigation" />
              <AddButton label="URL" cap="source-investigation" />
            </div>
            <button type="submit" className="btn btn-primary" disabled={!question.trim()}>
              Investigate
            </button>
          </div>
          {user?.walletAddress && (
            <span className={styles.walletBadge}>Wallet connected</span>
          )}
        </form>

        <div className={styles.examples}>
          <span className={styles.examplesLabel}>Try:</span>
          {EXAMPLE_PROMPTS.slice(0, 3).map((p) => (
            <button key={p} className={styles.exampleChip} onClick={() => setQuestion(p)}>
              {p}
            </button>
          ))}
        </div>
      </section>

      <section className={styles.statsRow}>
        <StatsCard data={data} budget={budget} />
      </section>

      <section className={styles.recent}>
        <div className={styles.recentHead}>
          <h2 className="app-section-title" style={{ marginBottom: 0 }}>Recent investigations</h2>
          {recent.length > 0 && <Link href="/history" className={styles.viewAll}>View all</Link>}
        </div>

        {loading ? (
          <p className="text-muted">Loading…</p>
        ) : recent.length === 0 ? (
          <EmptyState />
        ) : (
          <div className={styles.recentGrid}>
            {recent.slice(0, 3).map((inv) => (
              <Link
                key={inv.id}
                href={`/investigation/${inv.id}`}
                className={`card card-hover ${styles.recentCard}`}
              >
                <div className={styles.recentCardTop}>
                  <span className={`pill ${statusPill(inv)}`}>{label(inv.status)}</span>
                  <span className={styles.recentDate}>{date(inv.createdAt)}</span>
                </div>
                <p className={styles.recentQ}>&ldquo;{inv.question}&rdquo;</p>
                {inv.status === "completed" && (
                  <div className={styles.recentMeta}>
                    <span>{inv.confidence}% confidence</span>
                    <span>{inv.evidence.length} pieces of evidence</span>
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function AddButton({ label, cap }: { label: string; cap: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      className={styles.addBtn}
      title={`Add ${label}`}
      onClick={() => router.push(`/investigate?cap=${cap}`)}
    >
      {label}
    </button>
  );
}

function StatsCard({
  data,
  budget,
}: {
  data: DashboardData | null;
  budget: { spent: number; total: number; remaining: number } | null;
}) {
  const stats = [
    { label: "Investigations", value: data?.totalInvestigations ?? 0 },
    { label: "This week", value: data?.investigationsThisWeek ?? 0 },
    { label: "Evidence checks", value: data?.evidenceChecksPurchased ?? 0 },
    { label: "Avg confidence", value: data?.averageConfidence ? `${Math.round(data.averageConfidence)}%` : "—" },
  ];
  return (
    <div className={`card ${styles.statsCard}`}>
      <div className={styles.statsHeader}>
        <p className={styles.statsTitle}>Your investigations</p>
        {budget && (
          <span className={styles.budgetPill}>
            ${budget.remaining.toFixed(2)} remaining
          </span>
        )}
      </div>
      <div className={styles.statsGrid}>
        {stats.map((s) => (
          <div key={s.label} className={styles.statItem}>
            <span className={styles.statValue}>{s.value}</span>
            <span className={styles.statLabel}>{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className={`card ${styles.empty}`}>
      <div className={styles.emptyIcon} aria-hidden="true">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
      </div>
      <h3>No investigations yet</h3>
      <p className="text-muted">Ask something you&apos;re not sure about above.</p>
    </div>
  );
}

function greet(): string {
  const h = new Date().getHours();
  if (h < 12) return "morning";
  if (h < 18) return "afternoon";
  return "evening";
}
function date(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (now.getTime() - d.getTime() < 86400000) return "Today";
  return d.toLocaleDateString();
}
function label(s: string): string {
  return s.replace("_", " ");
}
function statusPill(inv: Investigation): string {
  switch (inv.status) {
    case "completed": return "pill-success";
    case "awaiting_payment":
    case "payment_pending":
    case "evidence_requested":
    case "evidence_received":
    case "planning":
    case "discovering":
    case "analyzing":
    case "cross_checking":
    case "created": return "pill-info";
    case "payment_failed":
    case "settlement_failed":
    case "evidence_unavailable":
    case "blocked":
    case "failed": return "pill-danger";
    default: return "pill-neutral";
  }
}
