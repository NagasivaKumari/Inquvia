export interface EvidenceService {
  id?: string;
  name?: string;
  capability?: string;
  description?: string;
  priceMicro?: number;
  priceUsdc?: number;
  paid?: boolean;
  endpoint?: string;
}

const directAnalysisCapabilities: Record<string, string> = {
  assess: "/api/evidence/assess",
  contradictions: "/api/evidence/contradictions",
  duplicates: "/api/evidence/duplicates",
  timeline: "/api/evidence/timeline",
  gaps: "/api/evidence/gaps",
};

function capabilityName(value: string): string {
  return value
    .trim()
    .replace(/^evidence-/, "")
    .replace(/^.*\//, "")
    .replace(/-investigation$/, "");
}

export function capabilityForService(service: EvidenceService): string {
  const declared = capabilityName(service.capability ?? service.id ?? "");
  const endpointType = capabilityName(service.endpoint?.match(/\/api\/(?:evidence|x402)\/([^/?#]+)/)?.[1] ?? "");
  const type = declared || endpointType;
  const direct = directAnalysisCapabilities[type] ?? directAnalysisCapabilities[endpointType];
  if (direct) return direct;
  const paidType = ["authenticity", "structured", "url", "image", "image-batch", "video", "document", "audio", "data", "claim"].includes(type)
    ? type
    : endpointType;
  if (paidType === "authenticity") return "image-investigation";
  if (paidType === "structured") return "data-investigation";
  if (paidType === "url") return "source-investigation";
  if (["image", "image-batch", "video", "document", "audio", "data", "claim"].includes(paidType)) {
    return `${paidType}-investigation`;
  }
  return "";
}
