import type { EvidenceItem, Investigation } from "../types";
import { callAIWithParts, parseAIJson, type AIPart } from "./ai";
import {
  AnalysisResult,
  heuristicAnalysis,
  clampConfidence,
  normalizeConclusion,
  readStoredText,
  readStoredFileBase64,
  VALID_RISKS,
} from "./analyze";

/**
 * Capability analyzer registry.
 *
 * Each atomic paid capability registers its OWN analysis pipeline here. The
 * pipelines differ in what they inspect (a live URL vs an image file vs a
 * PDF), how they build the AI prompt, and what findings they emphasise. The
 * registry lets the shared engine dispatch to the right analyzer purely from
 * the capability recorded on the investigation.
 *
 * All analyzers reuse the internal AI client (OpenAI/Gemini are internal
 * infrastructure; the USER pays Inquvia, not the AI provider).
 */

export type CapabilityAnalyzer = (
  inv: Investigation,
  evidence: EvidenceItem[]
) => Promise<AnalysisResult>;

const REGISTRY = new Map<string, CapabilityAnalyzer>();

export function registerAnalyzer(capabilityId: string, analyzer: CapabilityAnalyzer): void {
  REGISTRY.set(capabilityId, analyzer);
}

export function getAnalyzer(capabilityId?: string): CapabilityAnalyzer | undefined {
  if (!capabilityId) return undefined;
  return REGISTRY.get(capabilityId);
}

/* ── Shared helpers for analyzers ── */

interface AIRawAnalysis {
  conclusion?: string;
  confidence?: number | string;
  risk?: string;
  findings?: unknown;
  contradictions?: unknown;
  limitations?: unknown;
  uncertainty?: string;
  sourcesUsed?: unknown;
  conclusionText?: string;
}

function toStrArray(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  return v
    .filter((x): x is string => typeof x === "string")
    .map((s) => s.slice(0, 500));
}

/** Map raw AI JSON onto the shared AnalysisResult, falling back to the heuristic. */
function mergeAIRaw(
  inv: Investigation,
  evidence: EvidenceItem[],
  raw: AIRawAnalysis | null
): AnalysisResult {
  const base = heuristicAnalysis(inv, evidence);
  if (!raw) return base;

  const conclusion = normalizeConclusion(raw.conclusion) ?? base.conclusion;
  let confidence = base.confidence;
  if (typeof raw.confidence === "number") {
    confidence = clampConfidence(raw.confidence);
  } else if (typeof raw.confidence === "string") {
    const n = Number.parseFloat(raw.confidence);
    if (Number.isFinite(n)) confidence = clampConfidence(n);
  }

  const risk = raw.risk && VALID_RISKS.includes(raw.risk as never)
    ? (raw.risk as typeof base.risk)
    : base.risk;

  const aiFindings = toStrArray(raw.findings);
  const findings = aiFindings.length > 0 ? aiFindings : base.findings;

  const contradictions = toStrArray(raw.contradictions);
  const limitations = toStrArray(raw.limitations);

  const sourcesUsed = toStrArray(raw.sourcesUsed);
  const uncertainty = typeof raw.uncertainty === "string" ? raw.uncertainty : undefined;

  const conclusionText =
    typeof raw.conclusionText === "string" && raw.conclusionText
      ? raw.conclusionText
      : base.conclusionText;

  return {
    conclusion,
    conclusionText:
      conclusionText ||
      `Assessment: ${conclusion.replace(/_/g, " ").toUpperCase()}. ${limitations.length ? limitations.join(" ") : ""}`.trim(),
    confidence,
    risk,
    findings,
    contradictions:
      contradictions.length > 0 ? contradictions : base.contradictions,
    limitations:
      limitations.length > 0 ? limitations : base.limitations,
    uncertainty,
    sourcesUsed,
  };
}

async function runAnalysis(
  inv: Investigation,
  evidence: EvidenceItem[],
  systemPrompt: string,
  contextParts: AIPart[]
): Promise<AnalysisResult> {
  // Every analyzer sees the collected evidence findings.
  const evidenceText =
    evidence.length > 0
      ? evidence
          .map(
            (e, i) =>
              `${i + 1}. [${e.signal}] source=${e.source} finding=${e.finding} confidence=${e.confidence}`
          )
          .join("\n")
      : "No external evidence was acquired.";

  contextParts.push({ text: `QUESTION: ${inv.question}\n\nACQUIRED EVIDENCE:\n${evidenceText}` });

  const rawText = await callAIWithParts(systemPrompt, contextParts);
  const raw = parseAIJson<AIRawAnalysis>(rawText);
  return mergeAIRaw(inv, evidence, raw);
}

function firstTextInput(inv: Investigation): string | null {
  const input = inv.inputs.find((i) => i.type === "text" || i.type === "url");
  return input ? input.content : null;
}

/* ── CLAIM ── */

registerAnalyzer("claim-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's claim verification analyst. Assess whether the submitted claim is supported, contradicted, or unresolved, using only the acquired evidence and your internal knowledge. Be explicit about uncertainty. Do not claim a conclusion you cannot support. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const claim = firstTextInput(inv) ?? inv.question;
  return runAnalysis(inv, evidence, systemPrompt, [{ text: `CLAIM: ${claim}` }]);
});

/* ── IMAGE ── */

registerAnalyzer("image-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's image forensics analyst. Inspect the provided image for signs of manipulation, generative-AI artifacts, or provenance inconsistencies, together with the acquired evidence. Do not claim verified authenticity — express confidence honestly and state limitations. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const input = inv.inputs.find((i) => i.type === "image");
  const parts: AIPart[] = [];
  if (input?.filePath) {
    const file = readStoredFileBase64(input.filePath);
    if (file) parts.push({ file });
  }
  parts.push({ text: `IMAGE_CONTEXT: ${input?.content ?? firstTextInput(inv) ?? ""}` });
  return runAnalysis(inv, evidence, systemPrompt, parts);
});

/* ── VIDEO ── */

registerAnalyzer("video-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's video forensics analyst. Assess the submitted video for temporal consistency, manipulation, or context issues using the video content (when provided) and the acquired evidence. Express confidence honestly; explicit uncertainty is expected. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const input = inv.inputs.find((i) => i.type === "video");
  const parts: AIPart[] = [];
  // Video inline multimodal is only sent when the file is small enough for the
  // provider; otherwise the analysis runs on metadata + acquired evidence.
  if (input?.filePath) {
    const file = readStoredFileBase64(input.filePath);
    if (file) parts.push({ file });
  }
  parts.push({ text: `VIDEO_CONTEXT: ${input?.content ?? firstTextInput(inv) ?? ""}` });
  return runAnalysis(inv, evidence, systemPrompt, parts);
});

/* ── DOCUMENT ── */

registerAnalyzer("document-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's document forensics analyst. Extract claims from the provided document, identify internal inconsistencies, and flag suspicious or altered content, together with acquired evidence. Express confidence honestly. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const input = inv.inputs.find((i) => i.type === "document");
  const parts: AIPart[] = [];
  let extractedText: string | null = null;
  if (input?.filePath) {
    extractedText = readStoredText(input.filePath);
    if (!extractedText) {
      const file = readStoredFileBase64(input.filePath);
      if (file) parts.push({ file });
    }
  }
  if (extractedText) {
    parts.push({ text: `DOCUMENT_TEXT:\n${extractedText}` });
  } else if (!parts.some((p) => p.file)) {
    parts.push({ text: `DOCUMENT_CONTEXT: ${input?.content ?? firstTextInput(inv) ?? ""}` });
  }
  return runAnalysis(inv, evidence, systemPrompt, parts);
});

/* ── SOURCE ── */

registerAnalyzer("source-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's web source credibility analyst. Evaluate the submitted URL using the live web inspection data (DNS, SSL, HTTP, content snippet) and the acquired evidence. Assess credibility signals, not absolute verification. Express confidence honestly. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const urlInput = inv.inputs.find((i) => i.type === "url");
  const inspection = inv as unknown as { webInspection?: Record<string, unknown> };
  const context = [
    `URL: ${urlInput?.content ?? firstTextInput(inv) ?? inv.question}`,
    inspection.webInspection
      ? `LIVE_WEB_INSPECTION:\n${JSON.stringify(inspection.webInspection, null, 2)}`
      : "No live web inspection was performed.",
  ];
  return runAnalysis(inv, evidence, systemPrompt, [{ text: context.join("\n\n") }]);
});

/* ── DATA ── */

registerAnalyzer("data-investigation", async (inv, evidence) => {
  const systemPrompt =
    "You are Inquvia's structured-data analyst. Inspect the submitted CSV/JSON dataset for anomalies, inconsistencies, missing values, or suspicious patterns, together with acquired evidence. Express confidence honestly. Return ONLY JSON: { conclusion: 'likely_genuine'|'likely_misleading'|'suspicious'|'insufficient_evidence'|'inconclusive', confidence: number 0-100, findings: string[], contradictions: string[], limitations: string[], uncertainty: string, sourcesUsed: string[], risk: 'low'|'moderate'|'high'|'unknown' }.";
  const input = inv.inputs.find((i) => i.type === "data" || i.type === "text");
  let content: string | null = null;
  if (input?.filePath) content = readStoredText(input.filePath, 30000);
  const dataContext =
    content ?? input?.content ?? inv.question;
  return runAnalysis(inv, evidence, systemPrompt, [{ text: `DATA_CONTEXT:\n${dataContext}` }]);
});