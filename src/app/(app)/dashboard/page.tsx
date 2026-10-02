"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Investigation } from "@/lib/types";
import { API_BASE, APP_NAME, PAID_CAPABILITIES } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { capabilityForService, type EvidenceService } from "@/lib/dashboard-capabilities";
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

interface InvestigationCardItem {
  id: string;
  kind: string;
  price: string;
  name: string;
  description: string;
  inputs?: readonly string[];
  href: string;
}

export default function DashboardPage() {
  const router = useRouter();
  const [data, setData] = useState<DashboardData | null>(null);
  const [user, setUser] = useState<{ name: string; walletAddress?: string; walletNetwork?: string } | null>(null);
  const [budget, setBudget] = useState<{ spent: number; total: number; remaining: number } | null>(null);
  const [services, setServices] = useState<EvidenceService[]>([]);
  const [question, setQuestion] = useState("");
  const [recentLoading, setRecentLoading] = useState(true);

  useEffect(() => {
    // Fire all requests independently — each section renders as its data arrives.
    apiFetch(`${API_BASE}/api/dashboard`)
      .then((r) => r.json())
      .then((d) => { setData(d); setRecentLoading(false); })
      .catch(() => setRecentLoading(false));

    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((me) => setUser(me.user ?? null))
      .catch(() => { });

    apiFetch(`${API_BASE}/api/user`)
      .then((r) => r.json())
      .then((b) => setBudget(b.budget ?? null))
      .catch(() => { });

    apiFetch(`${API_BASE}/api/providers`)
      .then((r) => r.json())
      .then((providers) => {
        if (Array.isArray(providers.services) && providers.services.length > 0) {
          setServices(providers.services);
        }
      })
      .catch(() => { });
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    router.push(`/investigate?q=${encodeURIComponent(question.trim())}`);
  };

  const firstName = user?.name?.split(" ")[0] ?? "there";
  const recent = data?.recentInvestigations ?? [];

  // If dynamic services are returned from /api/providers, use them. Otherwise, default immediately to Inquvia's core investigation capabilities.
  const cards: InvestigationCardItem[] = services.length > 0
    ? services.map((service, index) => {
        const cap = capabilityForService(service) || "claim-investigation";
        const price = typeof service.priceUsdc === "number"
          ? `$${service.priceUsdc.toFixed(2)} USDC`
          : typeof service.priceMicro === "number"
            ? `$${(service.priceMicro / 1_000_000).toFixed(2)} USDC`
            : service.paid === false ? "Included" : "$0.05 USDC";
        return {
          id: service.id ?? service.name ?? `srv-${index}`,
          kind: service.capability ?? cap.replace("-investigation", ""),
          price,
          name: service.name ?? "Evidence service",
          description: service.description ?? "Evidence-backed analysis selected for your investigation.",
          inputs: (service as { capabilities?: readonly string[]; inputTypes?: readonly string[] }).capabilities ?? (service as { inputTypes?: readonly string[] }).inputTypes,
          href: `/investigate?cap=${encodeURIComponent(cap)}&service=${encodeURIComponent(service.name ?? "Evidence check")}`,
        };
      })
    : PAID_CAPABILITIES.map((cap) => ({
        id: cap.id,
        kind: cap.id.replace("-investigation", "").replace(/-/g, " "),
        price: "$0.05 USDC",
        name: cap.title,
        description: cap.description,
        inputs: cap.inputTypes,
        href: `/investigate?cap=${encodeURIComponent(cap.id)}`,
      }));

  return (
    <div className={styles.page}>
      <div className={styles.greeting}>
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
              <AddButton label="Contradictions" cap="evidence-contradictions" />
              <AddButton label="Duplicates" cap="evidence-duplicates" />
            </div>
            <button type="submit" className="btn btn-primary" disabled={!question.trim()}>
              Investigate
            </button>
          </div>
          {user?.walletAddress && (
            <span className={styles.walletBadge}>Wallet connected</span>
          )}
        </form>
      </section>

      <section className={styles.statsRow}>
        <StatsCard data={data} budget={budget} />
      </section>

      <section className={styles.services}>
        <div className={styles.servicesHead}>
          <div>
            <p className={styles.sectionEyebrow}>Available investigations</p>
            <h2 className="app-section-title" style={{ marginBottom: 0 }}>
              What Inquvia can check
            </h2>
          </div>
          <span className={styles.serviceCount}>{cards.length} available</span>
        </div>

        <div className={styles.servicesGrid}>
          {cards.map((card) => (
            <Link
              key={card.id}
              href={question.trim() ? `${card.href}&q=${encodeURIComponent(question.trim())}` : card.href}
              className={`card card-hover ${styles.serviceCard}`}
            >
              <div className={styles.serviceTop}>
                <span className={styles.serviceKind}>{card.kind}</span>
                <span className={styles.servicePrice}>{card.price}</span>
              </div>
              <h3>{card.name}</h3>
              <p>{card.description}</p>
              {card.inputs && card.inputs.length > 0 && (
                <div className={styles.serviceInputs}>
                  {card.inputs.map((inp) => (
                    <span key={inp} className={styles.inputBadge}>{inp}</span>
                  ))}
                </div>
              )}
            </Link>
          ))}
        </div>
      </section>



      {(recentLoading || recent.length > 0) && (
        <section className={styles.recent}>
          <div className={styles.recentHead}>
            <h2 className="app-section-title" style={{ marginBottom: 0 }}>Recent investigations</h2>
            {recent.length > 0 && <Link href="/history" className={styles.viewAll}>View all</Link>}
          </div>

          {recentLoading ? (
            <div className={styles.recentSkeleton}>
              {[0, 1, 2].map((i) => <div key={i} className={styles.skeletonCard} />)}
            </div>
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
      )}
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
        <p className={styles.statsTitle}>Your activity</p>
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
