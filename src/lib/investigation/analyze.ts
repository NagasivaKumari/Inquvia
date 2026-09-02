import fs from "fs";
import type {
  AssessmentLabel,
  EvidenceItem,
  EvidenceGraph,
  Investigation,
  RiskLevel,
} from "../types";

/**
 * Shared analysis building blocks used by the capability analyzers and the
 * investigation engine. Pure helpers — no capability-specific logic lives
 * here; each atomic capability supplies its own analyzer (see analyzers.ts).
 */

export interface AnalysisResult {
  conclusion: AssessmentLabel;
  conclusionText: string;
  confidence: number;
  risk: RiskLevel;
  findings: string[];
  limitations: string[];
  contradictions: string[];
  uncertainty?: string;
  sourcesUsed?: string[];
}

/** The default deterministic analysis used when no capability analyzer or AI is available. */
export function heuristicAnalysis(
  inv: Investigation,
  evidence: EvidenceItem[]
): AnalysisResult {
  const supporting = evidence.filter(
    (e) => e.signal === "supporting" || e.supportsClaim
  );
  const contradicting = evidence.filter(
    (e) => e.signal === "contradictory" || e.contradictsClaim
  );

  return {
    conclusion:
      supporting.length >= 2 && contradicting.length === 0
        ? "likely_genuine"
        : contradicting.length >= 2
          ? "likely_misleading"
          : contradicting.length > 0 && supporting.length > 0
            ? "suspicious"
            : "inconclusive",
    conclusionText:
      evidence.length > 0
        ? `Based on ${evidence.length} acquired evidence item(s), ${supporting.length} supporting and ${contradicting.length} contradicting, Inquvia reached the assessment below.`
        : "Insufficient evidence acquired to render a supported assessment.",
    confidence: evidence.length
      ? Math.round(
          Math.max(0, Math.min(100, (supporting.length / evidence.length) * 100))
        )
      : 0,
    risk: contradictoryWeight(evidence),
    findings: evidence.map((e) => `${e.source}: ${e.finding}`),
    limitations:
      evidence.length < (inv.acquisitions?.length ?? 0)
        ? ["Some evidence checks did not complete"]
        : evidence.length === 0
          ? ["No external evidence was acquired", "AI analysis service was not available"]
          : ["Assessment is limited to the external evidence services that were configured and settled"],
    contradictions: contradicting.map((e) => e.finding),
  };

  function contradictoryWeight(items: EvidenceItem[]): RiskLevel {
    const c = items.filter(
      (e) => e.signal === "contradictory" || e.contradictsClaim
    ).length;
    if (c === 0) return "low";
    if (c <= 1) return "moderate";
    return "high";
  }
}

export function buildEvidenceGraph(
  inv: Investigation,
  evidence: EvidenceItem[]
): EvidenceGraph {
  const nodes: EvidenceGraph["nodes"] = [];
  const edges: EvidenceGraph["edges"] = [];
  const claimId = "node_claim";
  nodes.push({ id: claimId, kind: "claim", label: inv.question.slice(0, 80) });

  for (const e of evidence) {
    const sourceId = `node_source_${e.id}`;
    const evId = `node_ev_${e.id}`;
    nodes.push({ id: sourceId, kind: "source", label: e.source });
    nodes.push({ id: evId, kind: "evidence", label: e.type, evidenceId: e.id });
    edges.push({ from: evId, to: sourceId, relation: "derived_from" });
    edges.push({
      from: evId,
      to: claimId,
      relation:
        e.signal === "supporting" || e.supportsClaim
          ? "supports"
          : e.signal === "contradictory" || e.contradictsClaim
            ? "contradicts"
            : "related_to",
    });
  }

  const findingId = "node_finding";
  nodes.push({
    id: findingId,
    kind: "finding",
    label: inv.findings.length ? inv.findings[0] : "Analysis result",
  });
  edges.push({ from: findingId, to: claimId, relation: "verified_by" });

  nodes.push({
    id: "node_assessment",
    kind: "assessment",
    label: inv.conclusion,
  });
  edges.push({
    from: findTopEvidenceId(evidence) ?? findingId,
    to: "node_assessment",
    relation: "related_to",
  });

  return { nodes, edges };
}

function findTopEvidenceId(evidence: EvidenceItem[]): string | undefined {
  if (evidence.length === 0) return undefined;
  return `node_ev_${evidence[0].id}`;
}

export function clampConfidence(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.round(Math.min(100, Math.max(0, v)));
}

const VALID_CONCLUSIONS: AssessmentLabel[] = [
  "likely_genuine",
  "likely_misleading",
  "suspicious",
  "insufficient_evidence",
  "inconclusive",
];

export function normalizeConclusion(raw?: string): AssessmentLabel | undefined {
  if (!raw) return undefined;
  const v = raw.trim().toLowerCase().replace(/\s+/g, "_");
  return (VALID_CONCLUSIONS as string[]).includes(v)
    ? (v as AssessmentLabel)
    : undefined;
}

export const VALID_RISKS: RiskLevel[] = ["low", "moderate", "high", "unknown"];
export const VALID_SIGNALS = ["supporting", "contradictory", "uncertain"] as const;

/* ── Stored file helpers (capability analyzers consume stored inputs) ── */

/** Read a stored file's text content (for text/CSV/JSON documents). */
export function readStoredText(filePath: string, maxChars = 60000): string | null {
  try {
    if (!fs.existsSync(filePath)) return null;
    const buf = fs.readFileSync(filePath);
    if (buf.length > 2 * 1024 * 1024) return null; // only small text files
    return buf.toString("utf-8").replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, "").slice(0, maxChars);
  } catch {
    return null;
  }
}

/** Read a stored file as base64 for multimodal AI (Gemini inline_data). */
export function readStoredFileBase64(
  filePath: string
): { mimeType: string; base64: string } | null {
  try {
    if (!fs.existsSync(filePath)) return null;
    const buf = fs.readFileSync(filePath);
    if (buf.length === 0 || buf.length > 8 * 1024 * 1024) return null;
    return { mimeType: guessMime(filePath), base64: buf.toString("base64") };
  } catch {
    return null;
  }
}

function guessMime(filePath: string): string {
  const l = filePath.toLowerCase();
  if (l.endsWith(".pdf")) return "application/pdf";
  if (l.endsWith(".mp4")) return "video/mp4";
  if (l.endsWith(".webm")) return "video/webm";
  if (l.endsWith(".gif")) return "image/gif";
  if (l.endsWith(".png")) return "image/png";
  if (l.endsWith(".webp")) return "image/webp";
  if (l.endsWith(".json")) return "application/json";
  if (l.endsWith(".csv") || l.endsWith(".txt")) return "text/plain";
  return "image/jpeg";
}