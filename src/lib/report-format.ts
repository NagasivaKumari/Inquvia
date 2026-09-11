/**
 * Guarded, testable formatting for the report UI. Every function here tolerates
 * the shapes the backend actually stores — evidence items historically carry
 * NO `cost` field and `confidence: null` — so a valid investigation response
 * can never throw a render-time TypeError (e.g. `.toFixed` on undefined).
 *
 * Missing values render honestly ("Not available" / "n/a"), never as
 * synthesized or hardcoded evidence.
 */

export function formatUsdc(value: number | null | undefined, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "Not available";
}

export function formatConfidence(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value}%` : "n/a";
}

/** Look up a label in a Record, falling back to the raw value or a fallback. */
export function labelOr(
  labels: Record<string, string>,
  value: string | null | undefined,
  fallback = "Not available",
): string {
  if (value != null && value in labels) return labels[value];
  return value || fallback;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "Not available";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "Not available" : d.toLocaleString();
}

export function relationshipText(e: {
  signal?: string;
  supportsClaim?: boolean;
  contradictsClaim?: boolean;
}): string {
  if (e.signal === "supporting" || e.supportsClaim) return "supports the claim";
  if (e.signal === "contradictory" || e.contradictsClaim) return "contradicts the claim";
  return "no relationship asserted";
}

/** Exactly the evidence-item summary line rendered by the report. */
export function evidenceMetaLine(e: {
  signal?: string;
  supportsClaim?: boolean;
  contradictsClaim?: boolean;
  confidence?: number | null;
  cost?: number | null;
}): string {
  return `relationship: ${relationshipText(e)} · Confidence: ${formatConfidence(
    e.confidence,
  )} · Cost: ${formatUsdc(e.cost, 3)}`;
}