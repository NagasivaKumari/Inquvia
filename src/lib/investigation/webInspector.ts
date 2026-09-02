import dns from "dns/promises";
import https from "https";
import tls from "tls";
import { URL } from "url";

export interface LiveWebInspection {
  url: string;
  hostname: string;
  dnsRecords: string[];
  sslValid: boolean;
  sslIssuer?: string;
  sslDaysRemaining?: number;
  statusCode?: number;
  title?: string;
  metaDescription?: string;
  bodySnippet?: string;
  isOnline: boolean;
}

export async function inspectLiveUrl(targetUrl: string): Promise<LiveWebInspection | null> {
  try {
    let normalized = targetUrl.trim();
    if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
      normalized = "https://" + normalized;
    }

    const parsed = new URL(normalized);
    const hostname = parsed.hostname;

    // 1. DNS Resolution
    let dnsRecords: string[] = [];
    try {
      const addresses = await dns.resolve4(hostname);
      dnsRecords = addresses;
    } catch {
      try {
        const addresses = await dns.resolve(hostname);
        dnsRecords = addresses;
      } catch {
        dnsRecords = [];
      }
    }

    // 2. SSL Inspection
    let sslValid = false;
    let sslIssuer: string | undefined;
    let sslDaysRemaining: number | undefined;

    if (parsed.protocol === "https:") {
      try {
        const cert = await getCertificate(hostname, parseInt(parsed.port) || 443);
        if (cert) {
          sslValid = true;
          if (typeof cert.issuer === "object" && cert.issuer) {
            const org = cert.issuer.O || cert.issuer.CN;
            sslIssuer = Array.isArray(org) ? org[0] : org || "Trusted Authority";
          } else {
            sslIssuer = String(cert.issuer || "Trusted Authority");
          }
          if (cert.valid_to) {
            const expiry = new Date(cert.valid_to);
            sslDaysRemaining = Math.max(0, Math.round((expiry.getTime() - Date.now()) / (1000 * 60 * 60 * 24)));
          }
        }
      } catch {
        sslValid = false;
      }
    }

    // 3. Live HTTP Page Fetch
    let statusCode: number | undefined;
    let title: string | undefined;
    let metaDescription: string | undefined;
    let bodySnippet: string | undefined;
    let isOnline = false;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);

      const res = await fetch(normalized, {
        signal: controller.signal,
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InquviaForensics/2.0",
        },
      });
      clearTimeout(timeoutId);

      statusCode = res.status;
      isOnline = res.ok || res.status < 500;

      const html = await res.text();
      // Extract title
      const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
      if (titleMatch) title = titleMatch[1].trim();

      // Extract description
      const descMatch = html.match(/<meta[^>]*name=["']description["'][^>]*content=["']([^"']+)["']/i);
      if (descMatch) metaDescription = descMatch[1].trim();

      // Body text snippet
      const cleanText = html
        .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
        .replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();

      bodySnippet = cleanText.slice(0, 1000);
    } catch {
      isOnline = dnsRecords.length > 0;
    }

    return {
      url: normalized,
      hostname,
      dnsRecords,
      sslValid,
      sslIssuer,
      sslDaysRemaining,
      statusCode,
      title,
      metaDescription,
      bodySnippet,
      isOnline,
    };
  } catch {
    return null;
  }
}

function getCertificate(hostname: string, port = 443): Promise<tls.DetailedPeerCertificate | null> {
  return new Promise((resolve) => {
    const socket = tls.connect(
      {
        host: hostname,
        port,
        servername: hostname,
        rejectUnauthorized: false,
        timeout: 5000,
      },
      () => {
        const cert = socket.getPeerCertificate(true);
        socket.destroy();
        resolve(cert && Object.keys(cert).length > 0 ? cert : null);
      }
    );

    socket.on("error", () => {
      socket.destroy();
      resolve(null);
    });

    socket.on("timeout", () => {
      socket.destroy();
      resolve(null);
    });
  });
}
