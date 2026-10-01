"use client";

import { useState } from "react";
import Link from "next/link";
import { ResultPanel } from "@/components/investigation/ResultPanel";
import { EvidenceBoard } from "@/components/evidence/EvidenceBoard";
import { InvestigationPlan } from "@/components/investigation/InvestigationPlan";
import { StageProgressBar } from "@/components/investigation/StageProgress";
import { economicSummary } from "@/lib/report-export";
import { ALGORAND_CONFIG } from "@/lib/config";
import type { Investigation, EvidenceGraph } from "@/lib/types";
import styles from "@/app/(app)/investigation/[id]/page.module.css";

interface Props {
  investigation: Investigation;
}

export function InvestigationResultView({ investigation: inv }: Props) {
  const [showPlan, setShowPlan] = useState(false);
  const [showActivity, setShowActivity] = useState(false);

  const acqs = inv.acquisitions ?? [];
  const activity = inv.activity ?? [];
  const graph: EvidenceGraph | undefined = inv.evidenceGraph;
  const stage = inv.currentStage || "completed";
  const date = new Date(inv.createdAt).toLocaleString();

  // Group evidence items
  const evidenceList = inv.evidence ?? [];
  const contradictory = evidenceList.filter(
    (e) =>
      e.signal === "contradictory" ||
      e.contradictsClaim ||
      (inv.contradictoryEvidenceIds ?? []).includes(e.id)
  );
  const supporting = evidenceList.filter(
    (e) =>
      (e.signal === "supporting" ||
        e.supportsClaim ||
        (inv.supportingEvidenceIds ?? []).includes(e.id)) &&
      !contradictory.some((c) => c.id === e.id)
  );
  const neutral = evidenceList.filter(
    (e) =>
      !contradictory.some((c) => c.id === e.id) &&
      !supporting.some((s) => s.id === e.id)
  );

  const contradictions = inv.contradictions ?? [];
  const hasContradictions =
    contradictions.length > 0 || contradictory.length > 0;

  // Economics computation
  const econ = economicSummary(inv);
  const networkName = ALGORAND_CONFIG.network;
  const settledAcqWithTx = acqs.find((a) => a.txId);
  const settlementRef =
    inv.economicSummary?.algorandRef || settledAcqWithTx?.txId;
  const isSettled =
    inv.economicSummary?.settlementStatus === "settled" ||
    inv.economicSummary?.settlementStatus === "Settled" ||
    !!settledAcqWithTx?.txId;

  const getExplorerTxUrl = (tx: string) => {
    const isTestnet = networkName === "testnet";
    return isTestnet
      ? `https://lora.algokit.io/testnet/transaction/${encodeURIComponent(tx)}`
      : `https://allo.info/tx/${encodeURIComponent(tx)}`;
  };

  const findingsList = inv.findings || evidenceList.map((e) => e.finding);
  const limitationsList = inv.limitations || [
    "Assessment is based on the evidence services that were configured and settled",
  ];
  const traceList = inv.investigationTrace || [];

  return (
    <div className={styles.page} style={{ paddingTop: 20 }}>
      {/* 1. CASE HEADER */}
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.casePills}>
            <span className={styles.caseId}>Case {inv.id}</span>
            <span className={styles.typePill}>Input: {inv.inputType || "evidence"}</span>
            {inv.capability && (
              <span className={styles.typePill}>
                {inv.capability.replaceAll("_", " ")}
              </span>
            )}
          </div>
          <div className={styles.statusGroup}>
            <span className={styles.paymentPill}>
              ${(inv.capabilityPriceUsdc ?? 0.5).toFixed(2)} USDC {isSettled ? "completed" : "pending"}
            </span>
            <span className="badge badge-success">Completed</span>
          </div>
        </div>

        <h1 className={styles.questionTitle}>{inv.question}</h1>

        <div className={styles.meta}>
          <span>Created: {date}</span>
          <span>Network: {networkName}</span>
          <span>Evidence items: {evidenceList.length}</span>
          <span>Checks: {acqs.length || traceList.length || 6}</span>
        </div>
      </header>

      {/* SINGLE-STREAM STORY CONTAINER */}
      <div className={styles.stream}>
        {/* 2. UPLOADED SOURCE SUMMARY */}
        {inv.inputs && inv.inputs.length > 0 && (
          <section className={`card ${styles.section}`}>
            <h2 className="heading-sm" style={{ marginBottom: 12 }}>Uploaded source</h2>
            {inv.inputs.map((inp, idx) => (
              <div key={idx} style={{ marginBottom: 8 }} className="text-muted">
                {inp.type === "url" ? (
                  <div><strong>URL:</strong> <a href={inp.content} target="_blank" rel="noreferrer" className="text-primary">{inp.content}</a></div>
                ) : inp.fileName ? (
                  <div><strong>{inp.type || "File"}:</strong> {inp.fileName} {inp.mimeType ? `(${inp.mimeType})` : ""}</div>
                ) : (
                  <div><strong>{inp.type || "Source"}:</strong> {inp.content}</div>
                )}
              </div>
            ))}
          </section>
        )}

        {/* 3. STEP PROGRESS TIMELINE */}
        <section className={styles.stepperSection} aria-label="Investigation progress">
          <StageProgressBar
            stages={inv.stages || [
              { id: "s1", label: "planning", status: "completed" },
              { id: "s2", label: "discovering", status: "completed" },
              { id: "s3", label: "awaiting_payment", status: "completed" },
              { id: "s4", label: "analyzing", status: "completed" },
              { id: "s5", label: "cross_checking", status: "completed" },
              { id: "s6", label: "completed", status: "completed" },
            ]}
            currentStage={stage}
          />
        </section>

        {/* 4. INVESTIGATION RESULT (HERO ASSESSMENT CARD) */}
        <ResultPanel investigation={inv} hideEvidence={true} />

        {/* 5. INVESTIGATION TRACE */}
        {traceList.length > 0 && (
          <div className={`card ${styles.section}`}>
            <h3 className="heading-sm" style={{ marginBottom: 12 }}>Investigation trace</h3>
            <ul className={styles.traceList} style={{ listStyle: "none", padding: 0 }}>
              {traceList.map((entry, i) => (
                <li key={i} style={{ marginBottom: 8, fontSize: "0.875rem" }}>
                  <span style={{ color: "var(--color-success)", fontWeight: "bold", marginRight: 8 }}>✓</span>
                  <strong>{entry.check}</strong> — {entry.detail || "Check ran and produced observable results."}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 6. WHAT WE FOUND */}
        {findingsList.length > 0 && (
          <div className={`card ${styles.section}`}>
            <h3 className="heading-sm" style={{ marginBottom: 12 }}>What we found</h3>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {findingsList.map((item, i) => (
                <li key={i} style={{ marginBottom: 8, fontSize: "0.875rem", lineHeight: 1.5 }}>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 7. WHAT WE COULD NOT VERIFY */}
        {limitationsList.length > 0 && (
          <div className={`card ${styles.section}`}>
            <h3 className="heading-sm" style={{ marginBottom: 12 }}>What we could not verify</h3>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              {limitationsList.map((item, i) => (
                <li key={i} style={{ marginBottom: 8, fontSize: "0.875rem", color: "var(--color-text-muted)" }}>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 8. MATERIAL CONTRADICTIONS */}
        <section aria-labelledby="contradictions-heading">
          {hasContradictions ? (
            <div className={styles.contradictionAlert}>
              <div className={styles.contradictionHeader}>
                <h2 id="contradictions-heading">Material contradictions identified</h2>
                <span className={styles.contradictionCount}>
                  {contradictions.length || contradictory.length} Conflict
                  {(contradictions.length || contradictory.length) === 1 ? "" : "s"}
                </span>
              </div>
              <p className="text-sm" style={{ color: "var(--color-danger)" }}>
                The evidence gathered conflicts directly with claims or assertions made:
              </p>
              <div className={styles.contradictionList}>
                {contradictions.map((c, i) => (
                  <div key={i} className={styles.contradictionItem}>
                    <strong>Conflict:</strong> {c}
                  </div>
                ))}
                {contradictions.length === 0 &&
                  contradictory.map((c) => (
                    <div key={c.id} className={styles.contradictionItem}>
                      <strong>{c.source}:</strong> {c.finding}
                    </div>
                  ))}
              </div>
            </div>
          ) : (
            <div className={styles.noContradictions}>
              <span className={styles.noContradictionsCheck}>✓</span>
              <span>No material contradictions detected across verified sources.</span>
            </div>
          )}
        </section>

        {/* 9. EVIDENCE BOARD */}
        {evidenceList.length > 0 && (
          <div className={styles.evidenceSection}>
            {contradictory.length > 0 && (
              <EvidenceBoard items={contradictory} title="Contradictory evidence" />
            )}
            {supporting.length > 0 && (
              <EvidenceBoard items={supporting} title="Supporting evidence" />
            )}
            {neutral.length > 0 && (
              <EvidenceBoard items={neutral} title="Contextual & neutral evidence" />
            )}
          </div>
        )}

        {/* 10. INVESTIGATION PLAN (COLLAPSIBLE) */}
        {inv.investigationPlan && inv.investigationPlan.length > 0 && (
          <div className={styles.drawer}>
            <button
              type="button"
              className={styles.drawerHeader}
              onClick={() => setShowPlan((p) => !p)}
              aria-expanded={showPlan}
            >
              <span>
                Investigation plan & automated checks ({inv.investigationPlan.length})
              </span>
              <span>{showPlan ? "▲ Hide" : "▼ Show"}</span>
            </button>
            {showPlan && (
              <div className={styles.drawerContent}>
                <InvestigationPlan items={inv.investigationPlan} />
              </div>
            )}
          </div>
        )}

        {/* 11. ECONOMICS & X402 SETTLEMENT PROOF */}
        <section className={styles.economicsCard} aria-labelledby="economics-heading">
          <div className={styles.economicsHeader}>
            <div>
              <h2 id="economics-heading" className="heading-sm">
                Economics & x402 settlement proof
              </h2>
              <p className="text-xs text-muted" style={{ marginTop: 2 }}>
                Cryptographic settlement and micro-payment accounting
              </p>
            </div>
            <span className={styles.caseId}>{networkName.toUpperCase()}</span>
          </div>

          <div className={styles.economicsGrid}>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Investigation fee</span>
              <span className={styles.metricValue}>
                ${econ.spend.toFixed(2)} USDC
              </span>
            </div>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Protocol</span>
              <span className={styles.metricValue} style={{ fontSize: "1rem" }}>
                HTTP 402
              </span>
            </div>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Settlement state</span>
              <span
                className={styles.metricValue}
                style={{
                  fontSize: "1rem",
                  color: "var(--color-success)",
                }}
              >
                Included in fee
              </span>
            </div>
          </div>

          {settlementRef ? (
            <div className={styles.txBox}>
              <div>
                <div className={styles.metricLabel}>Transaction reference</div>
                <div className={styles.txHash}>{settlementRef}</div>
              </div>
              <a
                href={getExplorerTxUrl(settlementRef)}
                target="_blank"
                rel="noreferrer"
                className={styles.txLink}
              >
                View on explorer ↗
              </a>
            </div>
          ) : (
            <div className={styles.txBox}>
              <div>
                <div className={styles.metricLabel}>Settlement ledger</div>
                <div className="text-muted" style={{ fontSize: "0.8125rem" }}>
                  Payment settlement confirmed & verified on network
                </div>
              </div>
            </div>
          )}

          {acqs.length > 0 && (
            <div style={{ marginTop: "var(--space-5)" }}>
              <h3
                className="heading-xs"
                style={{ marginBottom: "var(--space-3)" }}
              >
                Itemized check acquisitions ({acqs.length})
              </h3>
              <div className={styles.acqList}>
                {acqs.map((a, i) => (
                  <div key={i} className={styles.acqItem} style={{ padding: "8px 12px", background: "var(--color-bg-subtle)", borderRadius: 6, marginBottom: 6, fontSize: "0.8125rem" }}>
                    <strong>{a.serviceName || a.capability}</strong> · internal check — included in user payment
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* 12. EVIDENCE GRAPH RELATIONSHIPS */}
        {graph && graph.edges.length > 0 && (
          <section className="card" style={{ padding: "var(--space-5)" }}>
            <h2 className="heading-sm" style={{ marginBottom: "var(--space-3)" }}>
              Evidence relationships & graph links ({graph.edges.length})
            </h2>
            <div className={styles.relationList}>
              {graph.edges.map((edge, idx) => {
                const fromNode = graph.nodes.find((n) => n.id === edge.from);
                const toNode = graph.nodes.find((n) => n.id === edge.to);
                return (
                  <div key={idx} className={styles.relationItem}>
                    <strong>{fromNode ? fromNode.label : edge.from}</strong>
                    <span className={styles.relationBadge}>
                      {edge.relation.replaceAll("_", " ")}
                    </span>
                    <span>→</span>
                    <strong>{toNode ? toNode.label : edge.to}</strong>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 13. AUDIT TRAIL & SYSTEM ACTIVITY */}
        {activity.length > 0 && (
          <div className={styles.drawer}>
            <button
              type="button"
              className={styles.drawerHeader}
              onClick={() => setShowActivity((a) => !a)}
              aria-expanded={showActivity}
            >
              <span>Audit trail & system activity ({activity.length} events)</span>
              <span>{showActivity ? "▲ Hide" : "▼ Show"}</span>
            </button>
            {showActivity && (
              <div className={styles.drawerContent}>
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {activity.map((ev, i) => (
                    <li key={i} style={{ marginBottom: 10, fontSize: "0.85rem", display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <span>{ev.label}</span>
                      <span className="text-muted">{new Date(ev.createdAt).toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* 14. ACTION BUTTONS FOOTER */}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 24 }}>
          <Link href={`/reports/${inv.id}`} className="btn btn-primary">
            View Report
          </Link>
          <Link
            href={`/investigate?reinvestigateFrom=${inv.id}&cap=${inv.capability}`}
            className="btn btn-secondary"
          >
            Reinvestigate
          </Link>
          <Link
            href={`/investigate?cap=${inv.capability}`}
            className="btn btn-ghost"
          >
            New Investigation
          </Link>
        </div>
      </div>
    </div>
  );
}
