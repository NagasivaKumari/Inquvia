import type { EvidenceRequirement, EvidenceType, InputType } from "../types";

/**
 * Dynamic Evidence Planner.
 *
 * Determines WHAT evidence is required to answer a question for a given input
 * type. It produces only requirements (capability + reason) — never findings,
 * never fabricated evidence. Actual evidence comes exclusively through the
 * Evidence Acquisition Gateway after real discovery + x402 settlement.
 *
 * Different questions/inputs yield different requirements:
 *  - image  -> image provenance, source verification, reverse-image, metadata
 *  - video  -> video analysis, frame evidence, source provenance, metadata
 *  - url    -> domain/SSL inspection, content extraction, source verification
 *  - claim/text -> original source, independent sources, publication date, contradictory evidence
 */

interface PlannableCapability {
  capability: string;
  reason: string;
  type: EvidenceType;
}

const CAPABILITY_BANK: Record<string, PlannableCapability> = {
  image_provenance: { capability: "image_provenance", reason: "Determine where and when the image originates", type: "image" },
  source_verify: { capability: "source_verify", reason: "Verify the credibility and identity of the source", type: "url" },
  reverse_image: { capability: "reverse_image", reason: "Search for prior occurrences of the image across indices", type: "image" },
  image_metadata: { capability: "image_metadata", reason: "Inspect EXIF and metadata for consistency", type: "image" },
  video_analysis: { capability: "video_analysis", reason: "Analyze video content for manipulation or context", type: "video" },
  frame_evidence: { capability: "frame_evidence", reason: "Extract and verify key frames from the video", type: "video" },
  domain_lookup: { capability: "domain_lookup", reason: "Check domain registration, WHOIS and DNS telemetry", type: "url" },
  ssl_scan: { capability: "ssl_scan", reason: "Validate SSL certificate and security posture", type: "url" },
  content_extract: { capability: "content_extract", reason: "Extract and verify page content", type: "url" },
  claim_support: { capability: "claim_support", reason: "Find supporting evidence for the claim", type: "text" },
  contradictory_evidence: { capability: "contradictory_evidence", reason: "Find evidence that contradicts the claim", type: "text" },
  original_source: { capability: "original_source", reason: "Locate the original source of the claim", type: "text" },
  independent_source: { capability: "independent_source", reason: "Locate independent corroborating sources", type: "text" },
  data_consistency: { capability: "data_consistency", reason: "Validate structured data for consistency", type: "data" },
  document_verify: { capability: "document_verify", reason: "Verify document authenticity and issuer", type: "document" },
};

export function planEvidenceRequirements(
  question: string,
  inputs: InputType[]
): EvidenceRequirement[] {
  const seen = new Set<string>();
  const result: EvidenceRequirement[] = [];
  const add = (key: string) => {
    if (seen.has(key)) return;
    seen.add(key);
    const cap = CAPABILITY_BANK[key];
    if (!cap) return;
    result.push({
      id: `req_${seen.size}_${key}`,
      type: cap.type,
      capability: cap.capability,
      reason: cap.reason,
    });
  };

  const q = question.toLowerCase();
  const types = new Set(inputs);

  if (types.has("image") || /image|photo|picture/.test(q)) {
    add("image_provenance");
    add("source_verify");
    add("reverse_image");
    if (!/image|photo/.test(q) || types.has("image")) add("image_metadata");
  } else if (types.has("video") || /video|footage|clip/.test(q)) {
    add("video_analysis");
    add("frame_evidence");
    add("source_verify");
    add("image_metadata");
  } else if (types.has("document") || /document|pdf|file/.test(q)) {
    add("document_verify");
    add("source_verify");
  } else if (types.has("data") || /data|dataset|json|csv/.test(q)) {
    add("data_consistency");
    add("source_verify");
  }

  if (/http|url|website|site|domain|seller|store/.test(q) || types.has("url")) {
    add("domain_lookup");
    add("ssl_scan");
    add("content_extract");
    add("source_verify");
  }

  // Claims / general questions always need source + corroboration.
  add("original_source");
  add("claim_support");
  add("independent_source");
  if (/fake|misleading|scam|genuine|authentic|true/.test(q)) {
    add("contradictory_evidence");
  }

  return result.slice(0, 6).map((r, i) => ({ ...r, id: `req_${i + 1}` }));
}

/* ─────────────────────────────────────────────────────────────
 * Per-capability evidence planners.
 *
 * Each atomic x402 capability has its OWN requirement plan. These are the
 * genuinely distinct "what evidence do I need" rules for each paid endpoint —
 * they are not a shared planner parametrized by a type string.
 * ───────────────────────────────────────────────────────────── */

function makePlanner(keys: string[]) {
  const boost: Record<string, string[]> = {};
  const qs: Record<string, string> = {};
  return function plan(question: string, inputs: InputType[], force: string[] = []): EvidenceRequirement[] {
    const seen = new Set<string>();
    const result: EvidenceRequirement[] = [];
    const add = (key: string) => {
      if (seen.has(key)) return;
      seen.add(key);
      const cap = CAPABILITY_BANK[key];
      if (!cap) return;
      result.push({
        id: `req_${seen.size}_${key}`,
        type: cap.type,
        capability: cap.capability,
        reason: cap.reason,
      });
    };

    for (const key of [...force, ...keys]) add(key);

    const q = question.toLowerCase();
    for (const [key, pattern] of Object.entries(qs)) {
      if (seen.has(key)) continue;
      if (new RegExp(pattern).test(q)) add(key);
    }
    void boost;
    return result.slice(0, 6);
  };
}

/** Claim Investigation: original-source verification + corroboration. */
export const planClaimRequirements = makePlanner([
  "original_source",
  "claim_support",
  "independent_source",
  "contradictory_evidence",
]);

/** Image Investigation: provenance, prior occurrences, metadata integrity. */
export const planImageRequirements = makePlanner([
  "image_provenance",
  "reverse_image",
  "image_metadata",
  "source_verify",
]);

/** Video Investigation: content analysis, frame evidence, metadata. */
export const planVideoRequirements = makePlanner([
  "video_analysis",
  "frame_evidence",
  "image_metadata",
  "source_verify",
]);

/** Document Investigation: authenticity, issuer, source verification. */
export const planDocumentRequirements = makePlanner([
  "document_verify",
  "source_verify",
]);

/** Source Investigation: domain/SSL/content telemetry for a URL. */
export const planSourceRequirements = makePlanner([
  "domain_lookup",
  "ssl_scan",
  "content_extract",
  "source_verify",
]);

/** Data Investigation: structured-data consistency checks. */
export const planDataRequirements = makePlanner(["data_consistency", "source_verify"]);
