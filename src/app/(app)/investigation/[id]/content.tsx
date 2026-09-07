"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { acquirePaidEvidence } from "@/lib/x402/client";
import { WalletBadge } from "@/components/wallet/WalletBadge";
import type {
  Investigation,
  EvidenceAcquisition,
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
  const [walletAddress, setWalletAddress] = useState("");

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

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => setWalletAddress(d.user?.walletAddress ?? ""))
      .catch(() => {});
  }, []);

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
  const spentMicro = acqs
    .filter((a) => a.paymentState === "evidence_received")
    .reduce((sum, a) => sum + (a.amountMicro ?? 0), 0);

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
          <span>
            {acqs.filter((a) => a.paymentState === "evidence_received").length}{" "}
            evidence acquired
          </span>
          <span>${microToUsdc(spentMicro)} USDC spent on evidence</span>
        </div>
        {inv.blockReason && (
          <div className={styles.blocked}>
            <strong>Unable to complete:</strong> {inv.blockReason}
          </div>
        )}
      </header>

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
            limitations={inv.limitations}
            findings={inv.findings}
          />
        </div>
      </div>

      {/* ECONOMIC EVENTS */}
      <section className={`card ${styles.section}`}>
        <h2 className="heading-sm">Evidence acquisition</h2>
        {acqs.length === 0 ? (
          <p className="text-muted">
            No evidence services have been purchased yet.
          </p>
        ) : (
          <>
            <PaymentPanel
              inv={inv}
              acqs={acqs}
              walletAddress={walletAddress}
              onConnected={setWalletAddress}
              onRefresh={fetchData}
            />
            <div className={styles.acqList}>
              {acqs.map((a) => (
                <AcquisitionRow key={a.id} acq={a} />
              ))}
            </div>
          </>
        )}
      </section>

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
  limitations,
  findings,
}: {
  status: Investigation["status"];
  conclusion: AssessmentLabel;
  conclusionText: string;
  confidence: number;
  risk: RiskLevel;
  acquisitions: EvidenceAcquisition[];
  limitations: string[];
  findings: string[];
}) {
  const acquired = acquisitions.filter(
    (a) => a.paymentState === "evidence_received"
  );
  const supporting = acquired.filter(
    (a) => a.evidence?.signal === "supporting" || a.evidence?.supportsClaim
  ).length;
  const contradictory = acquired.filter(
    (a) => a.evidence?.signal === "contradictory" || a.evidence?.contradictsClaim
  ).length;
  const costMicro = acquired.reduce((s, a) => s + (a.amountMicro ?? 0), 0);

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
            <div><strong>{acquired.length}</strong><span>evidence acquired</span></div>
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

function PaymentPanel({
  inv,
  acqs,
  walletAddress,
  onConnected,
  onRefresh,
}: {
  inv: Investigation;
  acqs: EvidenceAcquisition[];
  walletAddress: string;
  onConnected: (addr: string) => void;
  onRefresh: () => void;
}) {
  const pending = acqs.filter((a) => a.paymentState === "payment_required");
  if (pending.length === 0) return null;

  const [busyId, setBusyId] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const approve = async (acq: EvidenceAcquisition) => {
    if (!walletAddress) {
      setError("Connect your Pera wallet to pay the evidence provider.");
      return;
    }
    if (!acq.resourceUrl) {
      setError("Provider payment endpoint not available.");
      return;
    }
    setBusyId(acq.id);
    setError("");
    setStatus("Awaiting wallet approval…");
    try {
      const result = await acquirePaidEvidence({
        address: walletAddress,
        endpoint: acq.resourceUrl,
        question: inv.question,
        capability: acq.capability,
      });
      setStatus("Payment submitted — verifying settlement on-chain…");
      const res = await apiFetch(`${API_BASE}/api/gateway/acquire`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          investigationId: inv.id,
          acquisitionId: acq.id,
          txId: result.txId,
          evidence: result.evidence,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to record acquisition");
      setStatus("Settlement verified — evidence received.");
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    } finally {
      setBusyId("");
      setStatus("");
    }
  };

  const decline = async (acq: EvidenceAcquisition) => {
    setBusyId(acq.id);
    setError("");
    try {
      const res = await apiFetch(`${API_BASE}/api/gateway/acquire/decline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          investigationId: inv.id,
          acquisitionId: acq.id,
        }),
      });
      if (!res.ok) throw new Error("Failed to decline");
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to decline");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className={styles.paymentPanel}>
      <h3 className="heading-sm">Payment Required</h3>
      <p className="text-muted">
        The following evidence providers require payment before they will return
        evidence. You pay the provider directly from your wallet.
      </p>
      {pending.map((acq) => (
        <div key={acq.id} className={styles.paymentRow}>
          <div className={styles.paymentInfo}>
            <div className={styles.providerName}>{acq.serviceName ?? "External provider"}</div>
            <div className="text-muted">
              Capability: {acq.capability.replaceAll("_", " ")} · {" "}{(
                acq.amountMicro / 1e6
              ).toFixed(4)} USDC · {" "}{acq.network} · {" "}
              Asset: {acq.assetId}
            </div>
            {acq.payTo && (
              <div className="text-xs text-muted">
                Recipient: {acq.payTo}
              </div>
            )}
          </div>
          <div className={styles.paymentActions}>
            <WalletBadge
              address={walletAddress || undefined}
              onConnected={onConnected}
              onDisconnected={() => onConnected("")}
              compact
            />
            <button
              type="button"
              className="btn btn-primary"
              disabled={Boolean(busyId)}
              onClick={() => approve(acq)}
            >
              {busyId === acq.id && status ? (
                <span>{status}</span>
              ) : (
                "Approve Payment"
              )}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={Boolean(busyId)}
              onClick={() => decline(acq)}
            >
              Decline
            </button>
          </div>
          {error && busyId === acq.id && (
            <div className={styles.error}>{error}</div>
          )}
        </div>
      ))}
    </div>
  );
}
