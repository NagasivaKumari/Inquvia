/** Self-contained HTML export for an investigation report.
 *
 * Pure and dependency-free (no React, no CSS import, no DOM): the browser
 * handler fetches inline-able content and passes it in as `embeds`; tests
 * can drive the same function with plain shapes. Anything that cannot be
 * reliably carried in a downloaded private artifact (video, audio, PDF,
 * or content that failed to load) is represented by a labeled, authorized
 * link to the source-serving endpoint — never embedded, and never reduced
 * to a bare `- video: file.mp4` stub.
 */
import { APP_NAME, API_BASE } from "./config";
import {
  labelOr,
  formatConfidence,
  formatDate,
  formatUsdc,
  evidenceMetaLine,
} from "./report-format";
import { ASSESSMENT_LABELS, RISK_LABELS, SIGNAL_LABELS } from "./types";
import type { Investigation, EvidenceAcquisition } from "./types";
import { sourceFamily } from "./source-mime";

/** Inline content a caller managed to load through the authenticated source
 * endpoint. Missing entries make the export fall back to the open-link form. */
export interface ReportEmbed {
  /** Data URL (e.g. "data:image/png;base64,…") of the original image. */
  imageDataUrl?: string;
  /** Raw text of text/structured sources, shown verbatim. */
  text?: string;
}

export function sourceUrl(invId: string, filePath?: string): string {
  if (!filePath) return "";
  return `${API_BASE}/api/sources/${invId}/${encodeURIComponent(filePath)}`;
}

export interface EconomicSummaryView {
  /** User payment for this investigation, from the settled payments recorded
   * at finalize (`economicSummary.totalSpend`) — never summed from internal
   * evidence records. */
  spend: number;
  /** Internal evidence checks/records performed (acquisition count). */
  checks: number;
  /** Paid downstream provider spend (only acquisitions settled on-chain). */
  downstreamSpend: number;
}

export function economicSummary(inv: Investigation): EconomicSummaryView {
  const acqs = inv.acquisitions ?? [];
  return {
    spend:
      inv.economicSummary?.totalSpend != null
        ? inv.economicSummary.totalSpend
        : (inv.capabilityPriceUsdc ?? 0),
    checks: acqs.length,
    downstreamSpend:
      acqs.filter((a) => a.txId).reduce((s, a) => s + (a.amountMicro ?? 0), 0) / 1e6,
  };
}

function esc(s: string | number | undefined | null): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Escape attribute value; also drops a trailing `.` so the link is visibly
 * a URL, not prose, when it lands inside a sentence. */
function attr(src: string): string {
  return esc(src);
}

/** Provenance line (format/dimensions/mode/size/MIME/EXIF) shown next to the
 * rendered original — kept separate from semantic evidence findings. */
function provenanceRows(f: {
  fileSignals?: Record<string, unknown>;
  mimeType?: string;
}): string[] {
  const sig = (f.fileSignals ?? {}) as Record<string, unknown>;
  const rows: string[] = [];
  if (sig.format) rows.push(`format=${sig.format}`);
  if (sig.width && sig.height) rows.push(`${sig.width}×${sig.height}px`);
  if (sig.mode) rows.push(`mode=${sig.mode}`);
  if (sig.fileSizeBytes != null) rows.push(`${sig.fileSizeBytes} bytes`);
  rows.push(`mime=${sig.mimeType ?? f.mimeType ?? "n/a"}`);
  if (sig.exifPresent != null) rows.push(`EXIF ${sig.exifPresent ? "present" : "not present"}`);
  if (sig.error) return [`metadata could not be extracted (${sig.error})`];
  return rows;
}

/** One file input, rendered as: provenance label → actual source
 * representation (embedded preview when inline-able and loaded, otherwise a
 * labeled authorized "open original" link). */
export function renderSource(invId: string, f: {
  type?: string;
  fileName?: string;
  mimeType?: string;
  filePath?: string;
  content?: string;
  fileSignals?: Record<string, unknown>;
}, embed?: ReportEmbed): string {
  const open = (label: string) =>
    `<a href="${attr(sourceUrl(invId, f.filePath))}" target="_blank" rel="noreferrer">${esc(label)}</a>`;
  const fileName = f.fileName ?? f.content ?? "source";
  const fam = sourceFamily(f.mimeType ?? "");

  let body: string;
  if (fam === "image") {
    const dataUrl = embed?.imageDataUrl;
    body = dataUrl
      ? `<a href="${attr(sourceUrl(invId, f.filePath))}" target="_blank" rel="noreferrer"><img src="${attr(dataUrl)}" alt="${esc(fileName)}" /></a>`
      : open("Open original image securely");
  } else if (fam === "video") {
    body = open("Open original video securely");
  } else if (fam === "audio") {
    body = open("Open original audio securely");
  } else if (fam === "pdf") {
    body = open("Open original PDF securely");
  } else if (fam === "text" || fam === "structured") {
    const text = embed?.text;
    body =
      (text != null ? `<pre><code>${esc(text)}</code></pre>` : "") +
      open(`Open original ${fileName !== "source" ? `file (${fileName})` : "file"}`);
  } else {
    body = open(`Open uploaded file (${fileName})`);
  }

  const prov = provenanceRows({ fileSignals: f.fileSignals, mimeType: f.mimeType });
  return [
    `<p class="provenance"><strong>${esc(f.type ?? "file")}:</strong> ${esc(fileName)}${f.mimeType ? ` (${esc(f.mimeType)})` : ""}${prov.length ? `<br>${prov.map(esc).join(" · ")}` : ""}</p>`,
    `<div class="source">${body}</div>`,
  ].join("\n");
}

/** Full standalone report. `embeds` maps filePath → inline content loaded
 * through the authenticated source endpoint. */
export function generateReportHtml(inv: Investigation, embeds: Record<string, ReportEmbed> = {}): string {
  const eco = economicSummary(inv);
  const url = inv.webInspection;

  const inputsHtml = (inv.inputs ?? [])
    .map((i) => {
      if (i.type === "url" || (i.content && !i.filePath && i.type === "text")) {
        if (i.type === "url") {
          return (
            `<p class="provenance"><strong>url:</strong> <a href="${attr(i.content)}" target="_blank" rel="noreferrer">${esc(i.content)}</a></p>` +
            `<p class="retrieved">Content retrieved from the URL: ${
              url?.bodySnippet
                ? esc(url.bodySnippet)
                : url?.access?.reason
                  ? `unavailable — ${esc(url.access.reason)}`
                  : "none — no content retrieved."
            }</p>`
          );
        }
        return `<p class="provenance"><strong>${esc(i.type)}:</strong> ${esc(i.content)}</p>`;
      }
      if (!i.filePath) {
        return `<p class="provenance"><strong>${esc(i.type)}:</strong> ${esc(i.content)}</p>`;
      }
      return renderSource(inv.id, i, embeds[i.filePath]);
    })
    .join("\n");

  const planHtml = (inv.investigationPlan ?? [])
    .map((p) => `<li><strong>${esc(p.capability)}</strong> — ${esc(p.reason)} (${formatUsdc(p.estimatedCost, 3)})</li>`)
    .join("\n");

  const rel = inv.evidenceRelationships;
  const relationshipNote =
    rel && !rel.established
      ? "No supporting or contradicting evidence relationship was established (zero counts do not indicate the claim was disproved)."
      : `${rel?.supporting ?? 0} supporting, ${rel?.contradicting ?? 0} contradicting.`;

  const evidenceHtml = (inv.evidence ?? [])
    .map(
      (e) =>
        `<li><strong>${esc(e.type)}</strong> — ${esc(labelOr(SIGNAL_LABELS, e.signal))} (<span class="evidence-meta">${esc(evidenceMetaLine(e))}</span>)<br><span class="evidence-meta">Source: ${esc(e.source)}</span><br><span class="finding">${esc(e.finding)}</span></li>`
    )
    .join("\n");

  const acquisitions = (inv.acquisitions ?? []).map(acqLine).join("\n");

  return [
    `<!doctype html>`,
    `<html lang="en">`,
    `<head>`,
    `<meta charset="utf-8">`,
    `<title>${esc(APP_NAME)} Report — ${esc(inv.id)}</title>`,
    `<style>`,
    `body{font-family:system-ui,Segoe UI,Roboto,sans-serif;color:#1a1a1a;margin:40px auto;max-width:900px;padding:0 24px;line-height:1.5}`,
    `h1{font-size:24px}h2{font-size:16px;text-transform:uppercase;letter-spacing:.04em;color:#555;border-bottom:1px solid #e5e5e5;padding-bottom:6px;margin-top:28px}`,
    `.case{color:#888;font-size:13px;margin-top:-10px}`,
    `.provenance{color:#555;font-size:13px;margin:12px 0 4px;word-break:break-word}`,
    `.provenance strong{color:#1a1a1a}`,
    `.source{margin:4px 0 14px}.source img{max-width:100%;max-height:480px;border:1px solid #ddd;border-radius:4px;display:block;margin-bottom:6px}`,
    `.source pre{background:#fafafa;border:1px solid #e5e5e5;border-radius:4px;padding:10px;font-size:12px;white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:400px;margin:4px 0 8px}`,
    `.retrieved{color:#666;font-size:13px;font-style:italic}`,
    `.evidence-meta{color:#888;font-size:12px}`,
    `.finding{color:#333}`,
    `ul{margin:8px 0}li{margin-bottom:8px}`,
    `a{color:#0b5fff}`,
    `</style>`,
    `</head>`,
    `<body>`,
    `<h1>${esc(APP_NAME)} Investigation Report</h1>`,
    `<p class="case">Case: ${esc(inv.id)} · ${esc(formatDate(inv.createdAt))}</p>`,
    `<h2>Case</h2>`,
    `<p>“${esc(inv.question)}”</p>`,
    `<h2>Uploaded source / provenance</h2>`,
    inputsHtml || `<p class="provenance">no uploaded files</p>`,
    `<h2>Investigation plan</h2>`,
    planHtml ? `<ul>${planHtml}</ul>` : `<p class="provenance">No investigation plan recorded.</p>`,
    `<h2>Evidence</h2>`,
    `<p class="provenance">Evidence relationships: ${esc(relationshipNote)}</p>`,
    evidenceHtml ? `<ul>${evidenceHtml}</ul>` : `<p class="provenance">No evidence was acquired.</p>`,
    `<h2>Contradictions</h2>`,
    (inv.contradictions ?? []).length
      ? `<ul>${(inv.contradictions ?? []).map((c) => `<li>${esc(c)}</li>`).join("\n")}</ul>`
      : `<p class="provenance">None identified.</p>`,
    `<h2>Conclusion</h2>`,
    `<p><strong>${esc(labelOr(ASSESSMENT_LABELS, inv.conclusion))}</strong> — ${esc(inv.conclusionText ?? "")}</p>`,
    `<p class="provenance">Confidence: ${esc(formatConfidence(inv.confidence))} · Risk: ${esc(labelOr(RISK_LABELS, inv.risk))}</p>`,
    `<h2>Limitations</h2>`,
    (inv.limitations ?? []).length
      ? `<ul>${(inv.limitations ?? []).map((l) => `<li>${esc(l)}</li>`).join("\n")}</ul>`
      : `<p class="provenance">No limitations identified.</p>`,
    `<h2>Economic trail</h2>`,
    `<p class="provenance">User payment: $${eco.spend.toFixed(4)} USDC · Evidence checks performed: ${eco.checks} · Downstream provider spend: $${eco.downstreamSpend.toFixed(4)} USDC</p>`,
    acquisitions ? `<ul>${acquisitions}</ul>` : "",
    `</body>`,
    `</html>`,
  ].join("\n");
}

function acqLine(a: EvidenceAcquisition): string {
  const charge = a.txId
    ? `$${((a.amountMicro ?? 0) / 1e6).toFixed(4)} USDC`
    : "internal check — included in user payment";
  return (
    `<li><strong>${esc(a.capability)}</strong> — ${esc(a.serviceName ?? "no service")} · ${charge} — ${esc(a.paymentState)}${a.txId ? ` (Tx: ${esc(a.txId)})` : ""}</li>`
  );
}