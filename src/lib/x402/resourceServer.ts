import {
  x402ResourceServer,
  x402HTTPResourceServer,
  HTTPFacilitatorClient,
  type HTTPAdapter,
  type HTTPRequestContext,
  type HTTPResponseInstructions,
  type HTTPProcessResult,
  type HTTPTransportContext,
} from "@x402/core/server";
import { ExactAvmScheme } from "@x402/avm/exact/server";
import {
  ALGORAND_MAINNET_CAIP2,
  ALGORAND_TESTNET_CAIP2,
  USDC_MAINNET_ASA_ID,
  USDC_TESTNET_ASA_ID,
  normalizeAlgorandNetwork,
} from "@x402/avm";
import {
  ALGORAND_CONFIG,
  ALGORAND_NETWORK_CAIP2,
  ORCHESTRATOR_CONFIG,
  getPaidCapability,
  type PaidCapability,
} from "../config";

/**
 * Inquvia's x402 RESOURCE SERVER FACTORY.
 *
 * Each atomic paid capability gets its OWN x402 resource server built from
 * this factory. Every resource uses the REAL `@x402/core` middleware: unpaid
 * requests get a standards-conformant HTTP 402 PAYMENT-REQUIRED declaration,
 * paid requests are authenticated through the GoPlausible facilitator and
 * settled through it. All resources share Inquvia's SINGLE payTo address and
 * carry the project challenge tag (x402-global-challenge).
 *
 * Resource servers are built lazily and memoized per capability endpoint.
 * When the payTo address is unconfigured, the gate reports an explicit
 * "not configured" state — never a fake or invented payment.
 */

export class GatewayUnconfiguredError extends Error {
  constructor() {
    super("Paid capabilities are not configured on this deployment");
    this.name = "GatewayUnconfiguredError";
  }
}

export interface GatewayGate {
  ok: boolean;
  /** HTTP response to send when not ok (HTTP 402 with real requirements, or an error). */
  response?: Response;
  /** Finalize settlement and return the paid response with the PAYMENT-RESPONSE header. */
  settle: (body?: unknown) => Promise<Response>;
}

/** Adapter mapping a Next.js Web Request into the x402 HTTPAdapter interface. */
class NextRequestAdapter implements HTTPAdapter {
  private readonly headers: Headers;
  constructor(private readonly req: Request) {
    this.headers = req.headers;
  }
  getHeader(name: string): string | undefined {
    return this.headers.get(name) ?? undefined;
  }
  getMethod(): string {
    return this.req.method;
  }
  getPath(): string {
    return new URL(this.req.url).pathname;
  }
  getUrl(): string {
    return this.req.url;
  }
  getAcceptHeader(): string {
    return this.getHeader("accept") ?? "";
  }
  getUserAgent(): string {
    return this.getHeader("user-agent") ?? "";
  }
  getQueryParams?(): Record<string, string | string[]> {
    return Object.fromEntries(new URL(this.req.url).searchParams.entries());
  }
  getQueryParam?(name: string): string | string[] | undefined {
    return new URL(this.req.url).searchParams.get(name) ?? undefined;
  }
  getBody?(): unknown {
    return undefined;
  }
}

/** Memoized resource servers, keyed by the capability id. */
const serverCache = new Map<string, Promise<x402HTTPResourceServer>>();

async function buildGateway(capability: PaidCapability): Promise<x402HTTPResourceServer> {
  const payTo = ORCHESTRATOR_CONFIG.payTo.trim();
  if (!payTo || capability.priceUsdc <= 0) {
    throw new GatewayUnconfiguredError();
  }

  const facilitatorUrl = ALGORAND_CONFIG.facilitatorUrl;
  if (!facilitatorUrl) {
    throw new Error("X402_FACILITATOR_URL is not configured");
  }

  const isTestnet = ALGORAND_CONFIG.network === "testnet";
  const network = normalizeAlgorandNetwork(ALGORAND_NETWORK_CAIP2);
  const networkConst = isTestnet ? ALGORAND_TESTNET_CAIP2 : ALGORAND_MAINNET_CAIP2;
  const assetId = isTestnet ? USDC_TESTNET_ASA_ID : USDC_MAINNET_ASA_ID;

  // Exact micro amount on-chain (USDC 6 decimals), so the price is unambiguous.
  const amountMicro = Math.round(capability.priceUsdc * 1e6);

  const facilitator = new HTTPFacilitatorClient({ url: facilitatorUrl });
  const server = new x402ResourceServer(facilitator);
  server.register(networkConst, new ExactAvmScheme());

  const routePattern = `POST ${capability.endpoint}`;
  const httpServer = new x402HTTPResourceServer(server, {
    [routePattern]: {
      accepts: {
        scheme: "exact",
        payTo,
        price: { asset: assetId, amount: String(amountMicro) } as const,
        network,
        maxTimeoutSeconds: 3600,
        extra: { description: capability.description },
      },
      resource: capability.endpoint,
      description: capability.description,
      mimeType: "application/json",
      // The x402-global-challenge tag is attached to the actual resource
      // server configuration so the capability is Bazaar-discoverable.
      tags: [ALGORAND_CONFIG.challengeTag],
    },
  });

  await httpServer.initialize();
  return httpServer;
}

function getGateway(capabilityId: string): Promise<x402HTTPResourceServer> {
  const capability = getPaidCapability(capabilityId);
  if (!capability) {
    return Promise.reject(new Error(`Unknown capability: ${capabilityId}`));
  }
  if (!serverCache.has(capabilityId)) {
    const promise = buildGateway(capability).catch((err) => {
      // Do not memoize a failed build: allow retry on the next request.
      serverCache.delete(capabilityId);
      throw err;
    });
    serverCache.set(capabilityId, promise);
  }
  return serverCache.get(capabilityId)!;
}

function toNextResponse(r: HTTPResponseInstructions): Response {
  const body =
    r.body === undefined || r.body === null
      ? null
      : typeof r.body === "string"
        ? r.body
        : JSON.stringify(r.body);
  const headers: Record<string, string> = {
    "content-type": r.isHtml ? "text/html" : "application/json",
    ...r.headers,
  };
  return new Response(body, { status: r.status, headers });
}

/**
 * Gate an incoming request against ONE atomic capability's x402 resource
 * server. Returns `{ ok: true }` with a `settle()` finalizer when the
 * client's payment is verified, or an HTTP response (typically 402) when
 * unpaid/errored.
 */
export async function gatePaidRequest(
  capabilityId: string,
  request: Request
): Promise<GatewayGate> {
  let httpServer: x402HTTPResourceServer;
  try {
    httpServer = await getGateway(capabilityId);
  } catch (err) {
    if (err instanceof GatewayUnconfiguredError) {
      return {
        ok: false,
        response: Response.json(
          { error: "Paid capabilities are not configured on this deployment" },
          { status: 503 }
        ),
        settle: async () =>
          Response.json(
            { error: "Paid capabilities are not configured" },
            { status: 503 }
          ),
      };
    }
    console.error("x402 gateway init failed:", err);
    return {
      ok: false,
      response: Response.json(
        { error: "Payment facilitator unavailable" },
        { status: 502 }
      ),
      settle: async () =>
        Response.json({ error: "Payment facilitator unavailable" }, { status: 502 }),
    };
  }

  const adapter = new NextRequestAdapter(request);
  const path = adapter.getPath();
  const context: HTTPRequestContext = {
    adapter,
    path,
    method: request.method,
    paymentHeader: adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment"),
  };

  const result: HTTPProcessResult = await httpServer.processHTTPRequest(context);

  switch (result.type) {
    case "payment-error":
      return { ok: false, response: toNextResponse(result.response), settle: async () => toNextResponse(result.response) };

    case "no-payment-required":
      // Route requires payment; this should not normally happen for a protected route.
      return {
        ok: false,
        response: Response.json({ error: "Payment required" }, { status: 402 }),
        settle: async () => Response.json({}, { status: 402 }),
      };

    case "payment-verified": {
      const settle = async (body: unknown): Promise<Response> => {
        const transportContext: HTTPTransportContext = {
          request: context,
          responseHeaders: { "content-type": "application/json" },
        };
        const outcome = await httpServer.processSettlement(
          result.paymentPayload,
          result.paymentRequirements,
          result.declaredExtensions,
          transportContext
        );
        if (!outcome.success) {
          return toNextResponse(outcome.response);
        }
        return toNextResponse({
          status: 200,
          headers: { ...outcome.headers, ...transportContext.responseHeaders },
          body: body ?? {},
        });
      };
      return { ok: true, settle };
    }
  }
}

/** Backward-compatible name for callers that imported the old gate. */
export const gateInvestigationRequest = gatePaidRequest;