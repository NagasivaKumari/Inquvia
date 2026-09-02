import type {
  DiscoveredService,
  DiscoveryResult,
  EvidenceRequirement,
  EvidenceType,
} from "../types";
import { EVIDENCE_GATEWAY_CONFIG, ALGORAND_CONFIG, ALGORAND_NETWORK_CAIP2 } from "../config";

/**
 * Service Discovery for the Evidence Acquisition Gateway.
 *
 * This module ONLY returns real, externally-described evidence services:
 *   - from a live discovery catalog URL, or
 *   - from an inline environment catalog.
 *
 * It NEVER fabricates providers. When no real service is found, it returns an
 * empty services list so the investigation enters `evidence_unavailable`.
 */

// USDC on Algorand has 6 decimal places.
const USDC_DECIMALS = 1e6;

function evTypeFromCapability(cap: string): EvidenceType {
  if (cap.includes("image") || cap.includes("provenance") && cap.includes("image")) return "image";
  if (cap.includes("video")) return "video";
  if (cap.includes("document")) return "document";
  if (cap.includes("url") || cap.includes("domain") || cap.includes("web")) return "url";
  if (cap.includes("data") || cap.includes("consistent")) return "data";
  return "text";
}

function parseInlineCatalog(catalog: string): DiscoveredService[] {
  const services: DiscoveredService[] = [];
  for (const rawLine of catalog.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    // format: name|url|capability1,capability2|price_usdc|description
    const parts = line.split("|").map((p) => p.trim());
    if (parts.length < 4) continue;
    const [name, url, capsRaw, priceRaw, description = ""] = parts;
    const capabilities = capsRaw.split(",").map((c) => c.trim()).filter(Boolean);
    const priceUnit = parseFloat(priceRaw);
    if (!name || !url || capabilities.length === 0 || Number.isNaN(priceUnit)) continue;
    if (!/^https:\/\//i.test(url)) continue;
    services.push({
      id: `svc_${capabilities[0]}_${services.length + 1}`,
      name,
      capabilities,
      evidenceTypes: capabilities.map(evTypeFromCapability),
      resourceUrl: url,
      network: ALGORAND_NETWORK_CAIP2,
      priceMicro: Math.round(priceUnit * USDC_DECIMALS),
      assetId: ALGORAND_CONFIG.usdcAsa,
      description: description || `External evidence service: ${name}`,
      discoveredAt: new Date().toISOString(),
    });
  }
  return services;
}

async function discoverFromUrl(): Promise<DiscoveredService[]> {
  const url = EVIDENCE_GATEWAY_CONFIG.discoveryUrl;
  if (!url) return [];
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    const res = await fetch(url, { signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return [];
    const data = (await res.json()) as {
      services?: Array<{
        name?: string;
        url?: string;
        resourceUrl?: string;
        capabilities?: string[];
        price?: string | number;
        priceMicro?: number;
        assetId?: string;
        description?: string;
        tags?: string[];
      }>;
    };
    const tag = EVIDENCE_GATEWAY_CONFIG.discoveryTag;
    const raw = data.services ?? [];
    const services: DiscoveredService[] = [];
    for (const s of raw) {
      // only services tagged for this challenge
      if (tag && Array.isArray(s.tags) && s.tags.length > 0 && !s.tags.includes(tag)) continue;
      const resourceUrl = s.resourceUrl ?? s.url ?? "";
      if (!/^https:\/\//i.test(resourceUrl)) continue;
      const capabilities = (s.capabilities ?? []).filter(Boolean);
      if (capabilities.length === 0) continue;
      const priceMicro =
        typeof s.priceMicro === "number"
          ? s.priceMicro
          : typeof s.price === "number"
            ? Math.round(s.price * USDC_DECIMALS)
            : typeof s.price === "string"
              ? Math.round(parseFloat(s.price) * USDC_DECIMALS)
              : Number.NaN;
      if (Number.isNaN(priceMicro)) continue;
      services.push({
        id: `svc_disc_${services.length + 1}`,
        name: s.name ?? resourceUrl,
        capabilities,
        evidenceTypes: capabilities.map(evTypeFromCapability),
        resourceUrl,
        network: ALGORAND_NETWORK_CAIP2,
        priceMicro,
        assetId: s.assetId ?? ALGORAND_CONFIG.usdcAsa,
        description: s.description ?? `External evidence service: ${s.name}`,
        discoveredAt: new Date().toISOString(),
      });
    }
    return services;
  } catch {
    return [];
  }
}

function capabilityMatches(need: string, serviceCaps: string[]): boolean {
  return serviceCaps.some(
    (c) => c === need || c.includes(need) || need.includes(c)
  );
}

export async function discoverServices(
  requirements: EvidenceRequirement[]
): Promise<DiscoveryResult> {
  const inline = EVIDENCE_GATEWAY_CONFIG.inlineCatalog;
  const fromUrl = inline ? [] : await discoverFromUrl();
  const all: DiscoveredService[] = inline ? parseInlineCatalog(inline) : fromUrl;

  const source: DiscoveryResult["source"] =
    all.length > 0 ? (inline ? "configured" : "bazaar") : "none";

  return {
    requirements,
    services: all,
    source,
    discoveredAt: new Date().toISOString(),
  };
}

/**
 * Match discovered services to the evidence requirements of an investigation.
 * Economic selection (requirement #17): among services that can fulfil the
 * requirement, pick the cheapest by priceMicro (USDC micro-units).
 */
export function selectServiceForRequirement(
  requirement: EvidenceRequirement,
  services: DiscoveredService[]
): DiscoveredService | undefined {
  const matches = services.filter(
    (s) =>
      s.evidenceTypes.includes(requirement.type) ||
      capabilityMatches(requirement.capability, s.capabilities)
  );
  if (matches.length === 0) return undefined;
  // ponytail: cheapest-first; add a value/capability-quality score if providers
  // ever expose quality/reliability metadata, not just price.
  return matches.reduce((cheapest, s) =>
    s.priceMicro < cheapest.priceMicro ? s : cheapest
  );
}
