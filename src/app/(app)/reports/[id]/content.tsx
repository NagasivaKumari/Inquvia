"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { Investigation, EvidenceAcquisition } from "@/lib/types";
import { ASSESSMENT_LABELS, RISK_LABELS, SIGNAL_LABELS } from "@/lib/types";
import { API_BASE, APP_NAME } from "@/lib/config";
import styles from "./page.module.css";

export default function ReportDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [investigation, setInvestigation] = useState<Investigation | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/investigations/${id}`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then(setInvestigation);
  }, [id]);

  const handleExport = () => {
    if (!investigation) return;
    const report = generateReportText(investigation);
    const blob = new Blob([report], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${investigation.id}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleShare = async () => {
    if (!investigation) return;
    const url = window.location.href;
    if (navigator.share) {
      await navigator.share({
        title: `${APP_NAME} Report: ${investigation.title}`,
        url,
      });
    } else {
      await navigator.clipboard.writeText(url);
      alert("Report link copied to clipboard");
    }
  };

  if (!investigation) {
    return <p className="text-muted animate-pulse">Loading report…</p>;
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href="/reports" className="text-sm text-muted">
          ← Back to Reports
        </Link>
        <h1 className="heading-lg">{investigation.title}</h1>
        <p className={styles.caseId}>Case {investigation.id}</p>
        <div className={styles.actions}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExport}>
            Export report
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleShare}>
            Share report
          </button>
        </div>
      </header>

      <ReportSection title="Case">
        <p>&ldquo;{investigation.question}&rdquo;</p>
      </ReportSection>

      <ReportSection title="Inputs">
        <ul>
          {investigation.inputs.map((input, i) => (
            <li key={i}>
              <strong>{input.type}:</strong> {input.content}
              {input.fileName && ` (${input.fileName})`}
            </li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection title="Investigation plan">
        <ul>
          {investigation.investigationPlan.map((p) => (
            <li key={p.id}>
              <strong>{p.capability}</strong> — {p.reason} (${p.estimatedCost.toFixed(3)})
            </li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection title="Evidence">
        {investigation.evidence.map((e) => (
          <div key={e.id} className={styles.evidenceItem}>
            <p><strong>{e.type}</strong> — {SIGNAL_LABELS[e.signal]}</p>
            <p className="text-sm text-muted">Source: {e.source}</p>
            <p>{e.finding}</p>
            <p className="text-xs text-muted">
              Confidence: {e.confidence}% · Cost: ${e.cost.toFixed(3)}
            </p>
          </div>
        ))}
      </ReportSection>

      {investigation.contradictions.length > 0 && (
        <ReportSection title="Contradictions">
          <ul>
            {investigation.contradictions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </ReportSection>
      )}

      <ReportSection title="Conclusion">
        <p className={styles.conclusion}>
          {ASSESSMENT_LABELS[investigation.conclusion]}
        </p>
        <p>{investigation.conclusionText}</p>
      </ReportSection>

      <ReportSection title="Confidence">
        <p>{investigation.confidence}% — Risk: {RISK_LABELS[investigation.risk]}</p>
      </ReportSection>

      <ReportSection title="Limitations">
        <ul>
          {investigation.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection title="Economic trail">
        <div className={styles.economic}>
          <div><strong>Checks purchased:</strong> {economicSummary(investigation).checks}</div>
          <div><strong>Total spend:</strong> ${economicSummary(investigation).spend.toFixed(4)} USDC</div>
        </div>
        {(investigation.acquisitions ?? []).map((a) => (
          <div key={a.id} className={styles.paymentRow}>
            <strong>{a.capability}</strong> — {a.serviceName ?? "No service"} · $
            {((a.amountMicro ?? 0) / 1e6).toFixed(4)}{" "}
            USDC — {a.paymentState}{" "}
            {a.txId && <span className={styles.ref}>Tx: {a.txId}</span>}
          </div>
        ))}
      </ReportSection>
    </div>
  );
}

function ReportSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`card ${styles.section}`}>
      <h2 className="heading-sm">{title}</h2>
      <div className={styles.sectionContent}>{children}</div>
    </section>
  );
}

function generateReportText(inv: Investigation): string {
  const acqs = inv.acquisitions ?? [];
  const eco = economicSummary(inv);
  const lines = [
    `${APP_NAME} Investigation Report`,
    `Case: ${inv.id}`,
    `Date: ${new Date(inv.createdAt).toLocaleString()}`,
    "",
    "CASE",
    inv.question,
    "",
    "CONCLUSION",
    ASSESSMENT_LABELS[inv.conclusion],
    inv.conclusionText,
    `Confidence: ${inv.confidence}%`,
    `Risk: ${RISK_LABELS[inv.risk]}`,
    "",
    "FINDINGS",
    ...inv.findings.map((f) => `- ${f}`),
    "",
    "LIMITATIONS",
    ...inv.limitations.map((l) => `- ${l}`),
    "",
    "ECONOMIC TRAIL",
    `Total spend: $${eco.spend.toFixed(4)} USDC`,
    `Checks: ${eco.checks}`,
    ...acqs.map(
      (a) =>
        `- ${a.capability} (${a.serviceName ?? "no service"}): $${(a.amountMicro ?? 0) / 1e6} USDC — ${a.paymentState}${a.txId ? ` (Tx: ${a.txId})` : ""}`
    ),
  ];
  return lines.join("\n");
}

function economicSummary(inv: Investigation): { spend: number; checks: number } {
  const acqs = inv.acquisitions ?? [];
  return {
    spend: acqs
      .filter((a) => a.paymentState === "evidence_received" || a.paymentState === "settled")
      .reduce((s, a) => s + (a.amountMicro ?? 0), 0) / 1e6,
    checks: acqs.length,
  };
}
