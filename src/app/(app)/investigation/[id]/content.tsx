"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
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

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div>
            <p className={styles.caseId}>Case {inv.id}</p>
            <h1 className="heading-lg">{inv.title}</h1>
            <p className={styles.question}>&ldquo;{inv.question}&rdquo;</p>
          </div>
          <StatusBadge status={inv.status} />
        </div>
        <div className={styles.meta}>
          <span>{date}</span>
          <span>Input: {inv.inputType}</span>
          {inv.capability && (
            <span>Capability: {inv.capability.replaceAll("_", " ")}</span>
          )}
          {inv.capabilityPriceUsdc != null && (
            <span>Paid: ${inv.capabilityPriceUsdc.toFixed(4)} USDC</span>
          )}
        </div>
        {inv.blockReason && (
          <div className={styles.blocked}>
            <strong>Unable to complete:</strong> {inv.blockReason}
          </div>
        )}
      </header>

      {/* UPLOADED SOURCE */}
      <SubmittedSource inv={inv} />

      {/* LEFT — timeline / RIGHT — assessment */}
      <div className={styles.layout}>
        <div className={styles.col}>
          <Timeline
            status={inv.status}
            currentStage={stage}
            acquisitions={acqs}
          />
        </div>

        <div className={`${styles.col} ${styles.colCenter}`}>
          <DiscoveryPanel discovery={discovery} />
          <EvidenceGraphPanel graph={graph} />
        </div>

        <div className={styles.col}>
          <AssessmentPanel
            status={inv.status}
            conclusion={inv.conclusion}
            conclusionText={inv.conclusionText}
            confidence={inv.confidence}
            risk={inv.risk}
            acquisitions={acqs}
            evidence={inv.evidence}
            limitations={inv.limitations}
            findings={inv.findings}
            paidMicro={Math.round(
              (inv.capabilityPriceUsdc ?? inv.economicSummary?.totalSpend ?? 0) * 1e6
            )}
          />
        </div>
      </div>

      {/* ECONOMIC EVENTS */}
      {acqs.length > 0 && (
        <section className={`card ${styles.section}`}>
          <h2 className="heading-sm">Evidence acquisition</h2>
          <div className={styles.acqList}>
            {acqs.map((a) => (
              <AcquisitionRow key={a.id} acq={a} />
            ))}
          </div>
        </section>
      )}

      {/* ACTIVITY */}
      {activity.length > 0 && (
        <section className={`card ${styles.section}`}>
          <h2 className="heading-sm">Activity</h2>
          <ActivityTimeline events={activity} />
        </section>
      )}

      <div className={styles.actions}>
        {inv.status === "completed" && (
          <Link href={`/reports/${inv.id}`} className="btn btn-primary">
            View Report
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
      .catch(() => {});
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
      {plain.length > 0 && (
        <ul className={styles.findings}>
          {plain.map((i, n) => (
            <li key={n}>
              <strong>{i.type}:</strong> {i.content}
            </li>
          ))}
        </ul>
      )}
      {files.map((f, i) => {
        const src = `${API_BASE}/api/investigations/${inv.id}/files/${encodeURIComponent(
          f.fileName ?? "file"
        )}`;
        const style: React.CSSProperties = { maxWidth: "100%", marginTop: 8 };
        const mime = (f.mimeType ?? "").toLowerCase();
        return (
          <div key={i} style={{ marginTop: 12 }}>
            <div className="text-muted">
              {f.type}: {f.fileName} {f.mimeType ? `(${f.mimeType})` : ""}
            </div>
            {f.type === "video" ? (
              <video controls preload="metadata" src={src} style={style} />
            ) : f.type === "audio" ? (
              <audio controls preload="metadata" src={src} style={style} />
            ) : f.type === "image" ? (
              <img src={src} alt={f.fileName ?? "uploaded image"} style={style} />
            ) : mime === "application/pdf" ? (
              <iframe
                src={src}
                title={f.fileName ?? "uploaded pdf"}
                style={{ width: "100%", height: 480, marginTop: 8, border: "1px solid var(--color-border-subtle)", borderRadius: "var(--radius-md)", background: "#fff" }}
              />
            ) : mime.startsWith("text/") || mime.includes("json") || mime.includes("csv") ? (
              <TextFileContent src={src} />
            ) : (
              <a href={src} target="_blank" rel="noreferrer">
                Open uploaded file
              </a>
            )}
          </div>
        );
      })}
    </section>
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
  acquisitions,
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
  acquisitions: EvidenceAcquisition[];
  evidence: EvidenceItem[];
  limitations: string[];
  findings: string[];
  paidMicro?: number;
}) {
  const acquiredCount = (evidence ?? []).filter(
    (e) => (e.status ?? "collected") === "collected"
  ).length;
  const legacyCostMicro = acquisitions
    .filter((a) => a.paymentState === "evidence_received")
    .reduce((s, a) => s + (a.amountMicro ?? 0), 0);
  const costMicro = paidMicro ?? legacyCostMicro;
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
            <div><strong>${microToUsdc(costMicro)}</strong><span>cost</span></div>
          </div>
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
            {acq.serviceName ?? "No service configured"} · $
            {microToUsdc(acq.amountMicro)} USDC
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
