"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { economicSummary } from "@/lib/report-export";
import { SourceViewer } from "@/components/sources/SourceViewer";
import { StageProgressBar } from "@/components/investigation/StageProgress";
import { ResultPanel } from "@/components/investigation/ResultPanel";
import { EvidenceBoard } from "@/components/evidence/EvidenceBoard";
import { InvestigationPlan } from "@/components/investigation/InvestigationPlan";
import { ALGORAND_CONFIG } from "@/lib/config";
import type {
  Investigation,
  EvidenceAcquisition,
  EvidenceItem,
  ActivityEvent,
  EvidenceGraph,
  DiscoveredService,
  AssessmentLabel,
  RiskLevel,
} from "@/lib/types";
import styles from "./page.module.css";

const STAGE_LABELS: Record<string, string> = {
  planning: "Investigation planned",
  discovering: "Services discovered",
  awaiting_payment: "Awaiting payment",
  analyzing: "Analyzing evidence",
  cross_checking: "Cross-checking",
  completed: "Assessment",
  blocked: "Blocked",
  failed: "Failed",
};

const ASSESSMENT: Record<AssessmentLabel, string> = {
  likely_genuine: "Likely Genuine",
  likely_misleading: "Likely Misleading",
  suspicious: "Suspicious",
  insufficient_evidence: "Insufficient Evidence",
  inconclusive: "Inconclusive",
  answered: "Answered",
};

const RISK: Record<RiskLevel, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  unknown: "Unknown",
};

const STATE_LABEL: Record<string, string> = {
  payment_required: "Payment required",
  awaiting_wallet: "Awaiting wallet",
  wallet_authorized: "Wallet authorized",
  payment_submitted: "Payment submitted",
  settling: "Settling",
  settled: "Settlement confirmed",
  queued: "Queued for processing",
  processing: "Processing video",
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

const STATE_TONE: Record<string, string> = {
  payment_required: styles.tonePending,
  awaiting_wallet: styles.tonePending,
  wallet_authorized: styles.toneInfo,
  payment_submitted: styles.toneInfo,
  settling: styles.toneInfo,
  settled: styles.toneInfo,
  queued: styles.tonePending,
  processing: styles.toneInfo,
  evidence_requested: styles.toneInfo,
  evidence_received: styles.toneOk,
  wallet_rejected: styles.toneBad,
  insufficient_balance: styles.toneBad,
  unsupported_network: styles.toneBad,
  payment_failed: styles.toneBad,
  settlement_failed: styles.toneBad,
  provider_unavailable: styles.toneWarn,
  evidence_request_failed: styles.toneBad,
};

function microToUsdc(micro: number): string {
  return ((micro ?? 0) / 1e6).toFixed(4);
}

export default function InvestigationPage() {
  const params = useParams();
  const id = params.id as string;
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/investigations/${id}`);
      if (!res.ok) throw new Error("Investigation not found");
      const data = await res.json();
      setInv(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!inv) return;
    const waitingForUser = inv.status === "awaiting_payment";
    if (
      inv.status === "completed" ||
      inv.status === "evidence_unavailable" ||
      inv.status === "failed" ||
      inv.status === "blocked" ||
      waitingForUser
    ) {
      return;
    }
    const interval = setInterval(fetchData, 1500);
    return () => clearInterval(interval);
  }, [fetchData, inv?.status]);

  if (error) {
    return (
      <div className="empty-state">
        <p>{error}</p>
        <Link href="/investigate" className="btn btn-primary" style={{ marginTop: 16 }}>
          Start new investigation
        </Link>
      </div>
    );
  }

  if (!inv) {
    return (
      <div className={styles.loading}>
        <div className={styles.loadingHeader}>
          <div className={`${styles.skeleton} ${styles.skeletonTitle}`} />
          <div className={`${styles.skeleton} ${styles.skeletonText}`} />
        </div>
        <p className="text-muted animate-pulse">Loading investigation…</p>
      </div>
    );
  }

  const acqs = inv.acquisitions ?? [];
  const activity = inv.activity ?? [];
  const discovery = inv.discovery;
  const graph: EvidenceGraph | undefined = inv.evidenceGraph;
  const stage = inv.currentStage;
  const date = new Date(inv.createdAt).toLocaleString();

  // Drawers state
  const [showPlan, setShowPlan] = useState(false);
  const [showActivity, setShowActivity] = useState(false);
  const [showDiscovery, setShowDiscovery] = useState(false);

  // Group evidence items
  const evidenceList = inv.evidence ?? [];
  const contradictory = evidenceList.filter(
    (e) => e.signal === "contradictory" || e.contradictsClaim || (inv.contradictoryEvidenceIds ?? []).includes(e.id)
  );
  const supporting = evidenceList.filter(
    (e) => (e.signal === "supporting" || e.supportsClaim || (inv.supportingEvidenceIds ?? []).includes(e.id)) && !contradictory.some((c) => c.id === e.id)
  );
  const neutral = evidenceList.filter(
    (e) => !contradictory.some((c) => c.id === e.id) && !supporting.some((s) => s.id === e.id)
  );

  const contradictions = inv.contradictions ?? [];
  const hasContradictions = contradictions.length > 0 || contradictory.length > 0;

  // Economics computation
  const econ = economicSummary(inv);
  const networkName = ALGORAND_CONFIG.network;
  const settledAcqWithTx = acqs.find((a) => a.txId);
  const settlementRef = inv.economicSummary?.algorandRef || settledAcqWithTx?.txId;
  const isSettled = inv.economicSummary?.settlementStatus === "settled" || !!settledAcqWithTx?.txId;

  // Explorer link builder
  const getExplorerTxUrl = (tx: string) => {
    const isTestnet = networkName === "testnet";
    return isTestnet
      ? `https://lora.algokit.io/testnet/transaction/${encodeURIComponent(tx)}`
      : `https://allo.info/tx/${encodeURIComponent(tx)}`;
  };

  const isActiveInvestigation = inv.status === "planning" || inv.status === "discovering" || inv.status === "analyzing" || inv.status === "cross_checking" || inv.status === "evidence_requested";

  return (
    <div className={styles.page}>
      {/* 1. CASE HEADER */}
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.casePills}>
            <span className={styles.caseId}>Case {inv.id}</span>
            <span className={styles.typePill}>Input: {inv.inputType}</span>
            {inv.capability && (
              <span className={styles.typePill}>{inv.capability.replaceAll("_", " ")}</span>
            )}
          </div>
          <div className={styles.statusGroup}>
            {inv.capabilityPriceUsdc != null && (
              <span className={styles.paymentPill}>
                ${inv.capabilityPriceUsdc.toFixed(2)} USDC {isSettled ? "• Settled" : ""}
              </span>
            )}
            <StatusBadge status={inv.status} />
          </div>
        </div>

        <h1 className={styles.questionTitle}>{inv.question}</h1>

        <div className={styles.meta}>
          <span>Created: {date}</span>
          <span>Network: {networkName}</span>
          <span>Evidence items: {evidenceList.length}</span>
          {acqs.length > 0 && <span>Checks: {acqs.length}</span>}
        </div>

        {inv.blockReason && (
          <div className={styles.blocked}>
            <strong>Unable to complete:</strong> {inv.blockReason}
          </div>
        )}
      </header>

      {/* SINGLE-STREAM STORY CONTAINER */}
      <div className={styles.stream}>
        {/* 2. SUBMITTED SOURCE */}
        <SubmittedSource inv={inv} />

        {/* 3. LIVE INVESTIGATION PROGRESS */}
        {inv.stages && inv.stages.length > 0 && (
          <section className={styles.stepperSection} aria-label="Investigation progress">
            <StageProgressBar stages={inv.stages} currentStage={stage} />
          </section>
        )}

        {/* 4. ASSESSMENT HERO */}
        {inv.status === "completed" ? (
          <ResultPanel investigation={inv} hideEvidence={true} />
        ) : (
          <div className="card" style={{ padding: "var(--space-6)" }}>
            <h2 className="heading-sm" style={{ marginBottom: "var(--space-2)" }}>Investigation in progress</h2>
            <p className="text-muted">
              Evidence is currently being collected and cross-examined. The final assessment, confidence score, and findings will be generated once completed.
            </p>
          </div>
        )}

        {/* 5. CONTRADICTION EXPERIENCE */}
        <section aria-labelledby="contradictions-heading">
          {hasContradictions ? (
            <div className={styles.contradictionAlert}>
              <div className={styles.contradictionHeader}>
                <h2 id="contradictions-heading">Material contradictions identified</h2>
                <span className={styles.contradictionCount}>
                  {contradictions.length || contradictory.length} Conflict{(contradictions.length || contradictory.length) === 1 ? "" : "s"}
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
                {contradictions.length === 0 && contradictory.map((c) => (
                  <div key={c.id} className={styles.contradictionItem}>
                    <strong>{c.type}:</strong> {c.finding}
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

        {/* 6. EVIDENCE BOARD (Grouped Categorical Sections) */}
        {evidenceList.length > 0 ? (
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
        ) : (
          <div className="card" style={{ padding: "var(--space-5)" }}>
            <h2 className="heading-sm">Evidence collection</h2>
            <p className="text-muted" style={{ fontSize: "0.875rem", marginTop: 4 }}>
              {inv.status === "completed" ? "No evidence items recorded for this investigation." : "Evidence records will appear here as they are acquired."}
            </p>
          </div>
        )}

        {/* 7. INVESTIGATION PLAN (Collapsible) */}
        {inv.investigationPlan && inv.investigationPlan.length > 0 && (
          <div className={styles.drawer}>
            <button
              type="button"
              className={styles.drawerHeader}
              onClick={() => setShowPlan((p) => !p)}
              aria-expanded={showPlan}
            >
              <span>Investigation plan & automated checks ({inv.investigationPlan.length})</span>
              <span>{showPlan ? "▲ Hide" : "▼ Show"}</span>
            </button>
            {showPlan && (
              <div className={styles.drawerContent}>
                <InvestigationPlan items={inv.investigationPlan} />
              </div>
            )}
          </div>
        )}

        {/* 8. ECONOMICS & X402 PROOF */}
        <section className={styles.economicsCard} aria-labelledby="economics-heading">
          <div className={styles.economicsHeader}>
            <div>
              <h2 id="economics-heading" className="heading-sm">Economics & x402 settlement proof</h2>
              <p className="text-xs text-muted" style={{ marginTop: 2 }}>
                Cryptographic settlement and micro-payment accounting
              </p>
            </div>
            <span className={styles.caseId}>{networkName.toUpperCase()}</span>
          </div>

          <div className={styles.economicsGrid}>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Investigation fee</span>
              <span className={styles.metricValue}>${econ.spend.toFixed(2)} USDC</span>
            </div>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Protocol</span>
              <span className={styles.metricValue} style={{ fontSize: "1rem" }}>HTTP 402</span>
            </div>
            <div className={styles.economicsMetric}>
              <span className={styles.metricLabel}>Settlement state</span>
              <span
                className={styles.metricValue}
                style={{
                  fontSize: "1rem",
                  color: isSettled ? "var(--color-success)" : "var(--color-warning)",
                }}
              >
                {isSettled ? "Settled on-chain" : inv.status === "awaiting_payment" ? "Awaiting payment" : "Included in fee"}
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
                  {isSettled ? "Internal micro-transaction recorded" : "Payment settlement pending confirmation"}
                </div>
              </div>
            </div>
          )}

          {/* Itemized acquisition breakdown */}
          {acqs.length > 0 && (
            <div style={{ marginTop: "var(--space-5)" }}>
              <h3 className="heading-xs" style={{ marginBottom: "var(--space-3)" }}>
                Itemized check acquisitions ({acqs.length})
              </h3>
              <div className={styles.acqList}>
                {acqs.map((a) => (
                  <AcquisitionRow key={a.id} acq={a} />
                ))}
              </div>
            </div>
          )}
        </section>

        {/* 9. DISCOVERED SERVICES (Collapsible if present) */}
        {discovery && (discovery.services ?? []).length > 0 && (
          <div className={styles.drawer}>
            <button
              type="button"
              className={styles.drawerHeader}
              onClick={() => setShowDiscovery((d) => !d)}
              aria-expanded={showDiscovery}
            >
              <span>Discovered evidence services ({discovery.services?.length ?? 0})</span>
              <span>{showDiscovery ? "▲ Hide" : "▼ Show"}</span>
            </button>
            {showDiscovery && (
              <div className={styles.drawerContent}>
                <DiscoveryPanel discovery={discovery} />
              </div>
            )}
          </div>
        )}

        {/* 10. EVIDENCE GRAPH RELATIONSHIPS (Lightweight list, if present) */}
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
                    <span className={styles.relationBadge}>{edge.relation.replaceAll("_", " ")}</span>
                    <span>→</span>
                    <strong>{toNode ? toNode.label : edge.to}</strong>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 11. ACTIVITY AUDIT TRAIL (Collapsible) */}
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
                <ActivityTimeline events={activity} />
              </div>
            )}
          </div>
        )}
      </div>

      <div className={styles.actions}>
        {inv.status === "completed" && (
          <Link href={`/reports/${inv.id}`} className="btn btn-primary">
            View Report
          </Link>
        )}
        {(inv.inputs ?? []).some((i) => i.filePath || i.type === "url" || i.type === "text") && (
          <Link
            href={`/investigate?reinvestigateFrom=${inv.id}&cap=${inv.capability ?? ""}`}
            className="btn btn-secondary"
          >
            Reinvestigate
          </Link>
        )}
        <Link href="/investigate" className="btn btn-secondary">
          New Investigation
        </Link>
      </div>
    </div>
  );
}

function TextFileContent({ src }: { src: string }) {
  const [text, setText] = useState("");
  useEffect(() => {
    let cancelled = false;
    apiFetch(src)
      .then((r) => (r.ok ? r.text() : ""))
      .then((t) => {
        if (!cancelled) setText(t.slice(0, 4000));
      })
      .catch(() => { });
    return () => {
      cancelled = true;
    };
  }, [src]);
  if (!text) return null;
  return (
    <pre
      style={{
        maxWidth: "100%",
        marginTop: 8,
        padding: 12,
        background: "var(--color-surface-subtle, #fafafa)",
        border: "1px solid var(--color-border-subtle)",
        borderRadius: "var(--radius-sm)",
        fontSize: "0.85rem",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {text}
    </pre>
  );
}

function SubmittedSource({ inv }: { inv: Investigation }) {
  const files = (inv.inputs ?? []).filter((i) => i.filePath);
  const plain = (inv.inputs ?? []).filter((i) => i.type === "text" || i.type === "url");
  if (files.length === 0 && plain.length === 0) return null;
  return (
    <section className={`card ${styles.section}`}>
      <h2 className="heading-sm">Uploaded source</h2>
      {plain.map((i, n) => (
        <div key={n} style={{ marginTop: 12 }}>
          {i.type === "url" ? (
            <UrlSourceInput input={i} inspection={inv.webInspection} />
          ) : (
            <div className="text-muted">
              <strong>{i.type}:</strong> {i.content}
            </div>
          )}
        </div>
      ))}
      {files.map((f, i) => {
        const hasSignals = !!(
          f.fileSignals &&
          (f.fileSignals as { format?: string }).format
        );
        return (
          <div key={i} style={{ marginTop: 12 }}>
            <div className="text-muted">
              {f.type}: {f.fileName} {f.mimeType ? `(${f.mimeType})` : ""}
            </div>
            {hasSignals && (
              <SignalsLine signals={f.fileSignals} />
            )}
            <SourceViewer invId={inv.id} input={f} />
          </div>
        );
      })}
    </section>
  );
}

/** File-level signals shown alongside a rendered source (provenance, kept
 * separate from the rendered original). */
function SignalsLine({ signals }: { signals?: Record<string, unknown> }) {
  if (!signals) return null;
  const s = signals as {
    format?: string;
    width?: number;
    height?: number;
    mode?: string;
    exifPresent?: boolean;
  };
  if (!s.format) return null;
  return (
    <div className="text-muted" style={{ fontSize: "0.8125rem" }}>
      {s.format}
      {s.width && s.height ? ` · ${s.width}×${s.height}px` : ""}
      {` · mode ${s.mode}`}
      {` · EXIF ${s.exifPresent ? "present" : "not present"}`}
    </div>
  );
}

/** URL input: show the submitted URL plainly, and the content actually
 * retrieved from it (webInspection) separately — never pretending retrieved
 * content is the original submitted source. */
function UrlSourceInput({
  input,
  inspection,
}: {
  input: Investigation["inputs"][number];
  inspection?: Investigation["webInspection"];
}) {
  const url = input.content;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="text-muted">
        <strong>url:</strong>{" "}
        <a href={url} target="_blank" rel="noreferrer">{url}</a>
      </div>
      {inspection ? (
        <div className="text-muted" style={{ fontSize: "0.875rem", marginTop: 8 }}>
          {inspection.title && <p><strong>Page title:</strong> {inspection.title}</p>}
          {inspection.bodySnippet ? (
            <p style={{ marginTop: 4 }}>{inspection.bodySnippet}</p>
          ) : inspection.access?.reason ? (
            <p style={{ marginTop: 4 }}>Content unavailable: {inspection.access.reason}</p>
          ) : null}
          {!inspection.bodySnippet && !inspection.access?.reason && (
            <p style={{ marginTop: 4 }}>No content was retrieved from this URL.</p>
          )}
        </div>
      ) : (
        <p className="text-muted" style={{ fontSize: "0.8125rem", marginTop: 4 }}>
          No content retrieved yet.
        </p>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: Investigation["status"] }) {
  const map: Record<string, string> = {
    created: "badge-neutral",
    planning: "badge-info",
    discovering: "badge-info",
    awaiting_payment: "badge-warning",
    payment_pending: "badge-info",
    evidence_requested: "badge-info",
    evidence_received: "badge-info",
    analyzing: "badge-info",
    cross_checking: "badge-info",
    completed: "badge-success",
    payment_failed: "badge-danger",
    settlement_failed: "badge-danger",
    evidence_unavailable: "badge-warning",
    blocked: "badge-danger",
    failed: "badge-danger",
  };
  return (
    <span className={`badge ${map[status] ?? "badge-neutral"}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

function Timeline({
  status,
  currentStage,
  acquisitions,
}: {
  status: Investigation["status"];
  currentStage?: string;
  acquisitions: EvidenceAcquisition[];
}) {
  const order = [
    "planning",
    "discovering",
    "awaiting_payment",
    "analyzing",
    "cross_checking",
    "completed",
  ];
  const acqDoneIdx = acquisitions.filter(
    (a) => a.paymentState === "evidence_received"
  ).length;

  let rendered: string[] = [];
  if (status === "evidence_unavailable" || status === "blocked") {
    rendered = [...order.slice(0, 2), "blocked"];
  } else if (
    status === "payment_failed" ||
    status === "settlement_failed" ||
    status === "failed"
  ) {
    rendered = [...order.slice(0, 3), "failed"];
  } else if (acqDoneIdx > 0) {
    rendered = order;
  } else {
    rendered = order.slice(0, 3);
  }

  return (
    <section className={`card ${styles.timelineCard}`}>
      <h2 className="heading-sm">Timeline</h2>
      <ol className={styles.timeline}>
        <li className={styles.done}>
          <div className={styles.tlDot} />
          <span>Claim received</span>
        </li>
        {rendered.map((s) => {
          const isCurrent = status !== "completed" && s === currentStage;
          const done =
            status === "completed" ||
            order.indexOf(s) < order.indexOf(currentStage ?? "");
          return (
            <li key={s} className={done ? styles.done : isCurrent ? styles.current : styles.pending}>
              <div className={styles.tlDot} />
              <span>{STAGE_LABELS[s] ?? s.replaceAll("_", " ")}</span>
              {isCurrent && <em className={styles.tlActive}>in progress</em>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function DiscoveryPanel({ discovery }: { discovery?: Investigation["discovery"] }) {
  if (!discovery) return null;
  const services: DiscoveredService[] = discovery.services ?? [];
  return (
    <section className={`card ${styles.section}`}>
      <h2 className="heading-sm">Discovered services</h2>
      {services.length === 0 ? (
        <p className="text-muted">No compatible services discovered.</p>
      ) : (
        <div className={styles.serviceList}>
          {services.map((s) => (
            <div key={s.id} className={styles.service}>
              <div className={styles.serviceTop}>
                <strong>{s.name}</strong>
                <span className="text-muted">${microToUsdc(s.priceMicro)} USDC</span>
              </div>
              <p className="text-muted">{s.description}</p>
              <div className={styles.tags}>
                {s.capabilities.map((c) => (
                  <span key={c} className={styles.tag}>{c}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function EvidenceGraphPanel({ graph }: { graph?: EvidenceGraph }) {
  if (!graph || graph.nodes.length === 0) return null;
  return (
    <section className={`card ${styles.section}`}>
      <h2 className="heading-sm">Evidence graph</h2>
      <ul className={styles.graphNodes}>
        {graph.nodes.map((n) => (
          <li key={n.id} className={`${styles.graphNode} ${styles["kind_" + n.kind] ?? ""}`}>
            <span className={styles.graphKind}>{n.kind}</span>
            {n.label}
          </li>
        ))}
      </ul>
      {graph.edges.length > 0 && (
        <p className="text-muted">
          {graph.edges.length} connection{graph.edges.length === 1 ? "" : "s"} between
          evidence nodes.
        </p>
      )}
    </section>
  );
}

function AssessmentPanel({
  status,
  conclusion,
  conclusionText,
  confidence,
  risk,
  evidence,
  limitations,
  findings,
  paidMicro,
}: {
  status: Investigation["status"];
  conclusion: AssessmentLabel;
  conclusionText: string;
  confidence: number;
  risk: RiskLevel;
  evidence: EvidenceItem[];
  limitations: string[];
  findings: string[];
  paidMicro?: number;
}) {
  const acquiredCount = (evidence ?? []).filter(
    (e) => (e.status ?? "collected") === "collected"
  ).length;
  const costMicro = paidMicro ?? 0;
  const evItems = (evidence ?? []) as EvidenceItem[];
  const supporting = evItems.filter(
    (e) => e.signal === "supporting" || e.supportsClaim
  ).length;
  const contradictory = evItems.filter(
    (e) => e.signal === "contradictory" || e.contradictsClaim
  ).length;

  return (
    <section className={`card ${styles.assessment}`}>
      <h2 className="heading-sm">Current assessment</h2>

      {status === "completed" ? (
        <>
          <div className={styles.confidence}>
            <span className={styles.pct}>{Math.round(confidence ?? 0)}%</span>
            <span className="text-muted">confidence</span>
          </div>
          <p className={styles.conclusion}>{ASSESSMENT[conclusion] ?? conclusion}</p>
          <div className={styles.riskLine}>
            <span className="text-muted">Risk:</span> {RISK[risk] ?? risk}
          </div>
          {conclusionText && (
            <p className="text-muted" style={{ marginTop: 8 }}>{conclusionText}</p>
          )}
          <div className={styles.stats}>
            <div><strong>{supporting}</strong><span>supporting</span></div>
            <div><strong>{contradictory}</strong><span>contradictory</span></div>
            <div><strong>{acquiredCount}</strong><span>evidence acquired</span></div>
            <div><strong>${microToUsdc(costMicro)}</strong><span>user payment</span></div>
          </div>
          {supporting === 0 && contradictory === 0 && (
            <p className="text-muted" style={{ marginTop: 8 }}>
              No supporting or contradicting evidence relationship was established.
              Zero counts mean no relationship was asserted — the evidence neither
              supported nor disproved the claim.
            </p>
          )}
        </>
      ) : (
        <p className="text-muted">
          Assessment will be generated once the investigation completes.
        </p>
      )}

      {findings.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 className={styles.subHead}>Key findings</h3>
          <ul className={styles.findings}>
            {findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {limitations.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <h3 className={styles.subHead}>Limitations</h3>
          <ul className={styles.findings}>
            {limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function AcquisitionRow({ acq }: { acq: EvidenceAcquisition }) {
  const tone = STATE_TONE[acq.paymentState] ?? styles.toneNeutral;
  return (
    <div className={styles.acqRow}>
      <div className={styles.acqHead}>
        <div>
          <strong>{acq.capability.replaceAll("_", " ")}</strong>
          <div className="text-muted">
            {acq.serviceName ?? "No service configured"} ·{" "}
            {acq.txId
              ? `${microToUsdc(acq.amountMicro)} USDC`
              : "internal check — included in user payment"}
          </div>
        </div>
        <span className={`${styles.stateChip} ${tone}`}>
          {STATE_LABEL[acq.paymentState] ?? acq.paymentState.replaceAll("_", " ")}
        </span>
      </div>
      <div className={styles.acqMeta}>
        {acq.txId && <span className={styles.tx}>Tx: {acq.txId}</span>}
        <span>Network: {acq.network}</span>
        <span>Asset: {acq.assetId}</span>
      </div>
      {acq.blockReason && (
        <p className={styles.blockReason}>{acq.blockReason}</p>
      )}
      {acq.evidence && (
        <div className={styles.acqEvidence}>
          <span
            className={
              acq.evidence.signal === "supporting"
                ? styles.sigOk
                : acq.evidence.signal === "contradictory"
                  ? styles.sigBad
                  : styles.sigWarn
            }
          >
            {acq.evidence.signal}
          </span>
          <span className="text-muted">{acq.evidence.finding}</span>
        </div>
      )}
    </div>
  );
}

function ActivityTimeline({ events }: { events: ActivityEvent[] }) {
  const sorted = [...events].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  return (
    <ol className={styles.activity}>
      {sorted.map((e) => (
        <li key={e.id} className={styles.activityItem}>
          <div className={styles.tlDot} />
          <div>
            <strong>{e.label}</strong>
            {e.detail && <div className="text-muted">{e.detail}</div>}
            <span className={styles.activityTime}>
              {new Date(e.createdAt).toLocaleString()}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
