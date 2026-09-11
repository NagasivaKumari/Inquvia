"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { Investigation, EvidenceAcquisition, InvestigationInput } from "@/lib/types";
import { ASSESSMENT_LABELS, RISK_LABELS, SIGNAL_LABELS } from "@/lib/types";
import { formatUsdc, formatConfidence, formatDate, labelOr, evidenceMetaLine } from "@/lib/report-format";
import { API_BASE, APP_NAME } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { SourceViewer } from "@/components/sources/SourceViewer";
import styles from "./page.module.css";

export default function ReportDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiFetch(`${API_BASE}/api/investigations/${id}`)
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data?.id) {
          setError(data?.error || "Report could not be loaded.");
          return;
        }
        setInvestigation(data as Investigation);
      })
      .catch(() => setError("Report could not be loaded."));
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
    if (error) {
      return (
        <div className="empty-state">
          <h1 className="heading-md">Report unavailable</h1>
          <p className="text-muted">{error}</p>
          <Link href="/history" className="btn btn-primary">Back to history</Link>
        </div>
      );
    }
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
          {(investigation.inputs ?? []).map((input, i) => (
            <li key={i}>
              <strong>{input.type}:</strong>{" "}
              {input.filePath ? (
                <FileReference input={input} invId={id} />
              ) : (
                input.content
              )}
            </li>
          ))}
        </ul>
      </ReportSection>

      <UploadedSource inv={investigation} />

      <ReportSection title="Investigation plan">
        <ul>
          {(investigation.investigationPlan ?? []).map((p) => (
            <li key={p.id}>
              <strong>{p.capability}</strong> — {p.reason} ({formatUsdc(p.estimatedCost, 3)})
            </li>
          ))}
        </ul>
      </ReportSection>

      <ReportSection title="Evidence">
        <EvidenceRelationships inv={investigation} />
        {(investigation.evidence ?? []).map((e) => (
          <div key={e.id} className={styles.evidenceItem}>
            <div className={styles.evidenceTop}>
              <p><strong>{e.type}</strong> — {labelOr(SIGNAL_LABELS, e.signal)}</p>
              <EvidenceOriginTag item={e} />
            </div>
            <p className="text-sm text-muted">Source: {e.source}</p>
            <p>{e.finding}</p>
            <p className="text-xs text-muted">{evidenceMetaLine(e)}</p>
          </div>
        ))}
      </ReportSection>

      {(investigation.contradictions ?? []).length > 0 && (
        <ReportSection title="Contradictions">
          <ul>
            {(investigation.contradictions ?? []).map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </ReportSection>
      )}

      <ReportSection title="Conclusion">
        <p className={styles.conclusion}>
          {labelOr(ASSESSMENT_LABELS, investigation.conclusion)}
        </p>
        <p>{investigation.conclusionText}</p>
      </ReportSection>

      <ReportSection title="Confidence">
        <p>{formatConfidence(investigation.confidence)} — Risk: {labelOr(RISK_LABELS, investigation.risk)}</p>
      </ReportSection>

      <ReportSection title="Limitations">
        {(investigation.limitations ?? []).length > 0 ? (
          <ul>
            {(investigation.limitations ?? []).map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No limitations identified.</p>
        )}
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

function fileUrl(inv: Investigation, fileName: string): string {
  return `${API_BASE}/api/investigations/${inv.id}/files/${encodeURIComponent(
    fileName
  )}`;
}

function sourceUrl(inv: Investigation, filePath?: string): string {
  if (!filePath) return "";
  return `${API_BASE}/api/sources/${inv.id}/${encodeURIComponent(filePath)}`;
}

/** Inline reference for an uploaded file input (opens the actual file). */
function FileReference({ input, invId }: { input: InvestigationInput; invId: string }) {
  if (!input.fileName) return <>{input.content}</>;
  const name = input.fileName;
  const src = input.filePath ? sourceUrl({ id: invId } as Investigation, input.filePath) : `${API_BASE}/api/investigations/${invId}/files/${encodeURIComponent(name)}`;
  return (
    <>
      {name}
      {" "}
      <a href={src} target="_blank" rel="noreferrer" className="text-sm">
        view
      </a>
    </>
  );
}

/**
 * Uploaded source: renders the actual submitted media, not a filename. Images
 * are inlined as real previews (MIME image/*) and open at full size in a new
 * tab when clicked. File-level provenance (format, dimensions, mode, size,
 * MIME, EXIF/PNG tags) is shown separately from semantic evidence findings.
 */
function UploadedSource({ inv }: { inv: Investigation }) {
  const files = (inv.inputs ?? []).filter((i) => i.filePath);
  const plain = (inv.inputs ?? []).filter((i) => i.type === "text" || i.type === "url");
  if (files.length === 0 && plain.length === 0) return null;
  return (
    <ReportSection title="Uploaded source">
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
            <ProvenancePanel input={f} />
          </div>
        );
      })}
    </ReportSection>
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

/** File-level provenance facts (format/dimensions/mode/size/MIME/EXIF/PNG
 * tags). Kept visually separate from semantic evidence; absence of EXIF is
 * reported as absence — never as proof of manipulation or authenticity. */
function ProvenancePanel({ input }: { input: InvestigationInput }) {
  const sig = (input.fileSignals ?? {}) as Record<string, unknown>;
  if (!input.filePath) return null;
  if (Object.keys(sig).length === 0) return null;
  if (sig.error) {
    return (
      <p className={`text-xs text-muted ${styles.provenance}`}>
        File metadata could not be extracted: {String(sig.error)}
      </p>
    );
  }
  const exif = typeof sig.exif === "object" && sig.exif ? (sig.exif as Record<string, string>) : null;
  const pngTags = Object.keys(sig)
    .filter((k) => k.startsWith("png_"))
    .map((k) => [k.slice(4).replace(/_/g, " "), String(sig[k])]);
  const rows: [string, string][] = [];
  if (sig.format) rows.push(["Format", String(sig.format)]);
  if (sig.width && sig.height) rows.push(["Dimensions", `${sig.width} × ${sig.height} px`]);
  if (sig.mode) rows.push(["Color mode", String(sig.mode)]);
  if (sig.fileSizeBytes != null) rows.push(["File size", `${Number(sig.fileSizeBytes).toLocaleString()} bytes`]);
  rows.push(["MIME type", String(sig.mimeType ?? input.mimeType ?? "n/a")]);
  if (sig.exifPresent != null) {
    rows.push([
      "EXIF metadata",
      sig.exifPresent
        ? `Present${exif && Object.keys(exif).length ? ` (${Object.entries(exif).map(([k, v]) => `${k}=${v}`).join(", ")})` : " (no camera/editor tags)"}`
        : "Not present",
    ]);
  }
  if (sig.hasGps) rows.push(["GPS", "Present"]);
  for (const [k, v] of pngTags) rows.push([`PNG ${k}`, v]);
  if (rows.length === 0) return null;
  return (
    <dl className={styles.provenance}>
      {rows.map(([k, v]) => (
        <div key={k} className={styles.provenanceRow}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
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

/** Supporting / contradicting counts with explicit semantics: zero counts
 * mean no relationship was established, not that the claim was disproved. */
function EvidenceRelationships({ inv }: { inv: Investigation }) {
  const rel = inv.evidenceRelationships;
  const items = inv.evidence ?? [];
  const supporting = rel?.supporting ?? items.filter((e) => e.signal === "supporting" || e.supportsClaim).length;
  const contradicting = rel?.contradicting ?? items.filter((e) => e.signal === "contradictory" || e.contradictsClaim).length;
  const established = rel?.established ?? (supporting > 0 || contradicting > 0);
  return (
    <div className={styles.relationshipNote}>
      <div className={styles.relationshipStats}>
        <span><strong>{supporting}</strong> supporting</span>
        <span><strong>{contradicting}</strong> contradicting</span>
      </div>
      {!established ? (
        <p className="text-sm">
          No supporting or contradicting evidence relationship was established by this
          investigation. Zero counts mean no relationship was asserted — the evidence
          neither supported nor disproved the claim.
        </p>
      ) : (
        <p className="text-sm">
          Counts reflect evidence items whose relationship to the claim was actually
          established during investigation.
        </p>
      )}
    </div>
  );
}

/** Tags an item with its evidentiary nature so file-level provenance
 * observations stay visually separate from semantic analysis findings. */
function EvidenceOriginTag({ item }: { item: { metadata?: Record<string, unknown> } }) {
  const meta = item.metadata ?? {};
  if (meta.evidenceUnavailable) {
    return <span className={`text-xs ${styles.originTag} ${styles.originUnavailable}`}>evidence unavailable</span>;
  }
  if (meta.origin === "evidence_service") {
    return <span className={`text-xs ${styles.originTag}`}>file-level observation</span>;
  }
  if (meta.origin === "user_submission") {
    return <span className={`text-xs ${styles.originTag}`}>user submission</span>;
  }
  return <span className={`text-xs ${styles.originTag}`}>analysis finding</span>;
}

function generateReportText(inv: Investigation): string {
  const acqs = inv.acquisitions ?? [];
  const eco = economicSummary(inv);
  const files = (inv.inputs ?? []).filter((i) => i.filePath);
  const provLines: string[] = [];
  for (const f of files) {
    const sig = (f.fileSignals ?? {}) as Record<string, unknown>;
    provLines.push(`- ${f.type}: ${f.fileName ?? f.content}`);
    if (sig.error) {
      provLines.push(`  metadata: could not be extracted (${sig.error})`);
    } else if (sig.format) {
      provLines.push(
        `  format=${sig.format}, ${sig.width}x${sig.height}, mode=${sig.mode}, ` +
        `size=${sig.fileSizeBytes} bytes, mime=${sig.mimeType ?? f.mimeType}, ` +
        `exif=${sig.exifPresent ? "present" : "not present"}`
      );
    }
  }
  const rel = inv.evidenceRelationships;
  const relationshipLines =
    rel && !rel.established
      ? [
          "Evidence relationships: no supporting or contradicting relationship was established " +
            "(zero counts do not indicate the claim was disproved).",
        ]
      : [`Evidence relationships: ${rel?.supporting ?? 0} supporting, ${rel?.contradicting ?? 0} contradicting.`];
  const lines = [
    `${APP_NAME} Investigation Report`,
    `Case: ${inv.id}`,
    `Date: ${formatDate(inv.createdAt)}`,
    "",
    "CASE",
    inv.question,
    "",
    "UPLOADED SOURCE / PROVENANCE",
    ...(provLines.length ? provLines : ["no uploaded files"]),
    "",
    "CONCLUSION",
    labelOr(ASSESSMENT_LABELS, inv.conclusion),
    inv.conclusionText,
    ...relationshipLines,
    `Confidence: ${formatConfidence(inv.confidence)}`,
    `Risk: ${labelOr(RISK_LABELS, inv.risk)}`,
    "",
    "FINDINGS",
    ...(inv.findings ?? []).map((f) => `- ${f}`),
    "",
    "LIMITATIONS",
    ...(inv.limitations ?? []).map((l) => `- ${l}`),
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