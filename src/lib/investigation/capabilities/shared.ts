import type { Investigation } from "../../types";
import {
  startCapabilityInvestigation,
  planCapability,
  discoverAndAcquire,
} from "../engine";
import { getInvestigation, saveInvestigation } from "../../db";
import type { CapabilityRunArgs } from "./types";

/** Invalid input for a capability handler (mapped to HTTP 400 by the route). */
export class InputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputError";
  }
}

/**
 * Shared orchestration used by every atomic capability. The capability itself
 * supplies its own planner (distinct evidence requirements) and its own
 * analyzer (registered in ../analyzers and dispatched by id). This is shared
 * plumbing for the state machine only — each capability's pipeline differs.
 */
export async function runCapability(
  capabilityId: string,
  args: CapabilityRunArgs,
  requirements: { capability: string; reason: string }[],
  title: string,
  beforeDiscover?: (inv: Investigation) => void
): Promise<Investigation> {
  const inv = await startCapabilityInvestigation({
    id: args.id,
    userId: args.userId,
    question: args.question,
    inputs: args.inputs,
    capability: capabilityId,
    title,
    idempotencyKey: args.idempotencyKey,
  });

  await planCapability(
    inv,
    requirements.map((r, i) => ({
      id: `req_${i + 1}`,
      type: r.capability.includes("image")
        ? "image"
        : r.capability.includes("video")
          ? "video"
          : r.capability.includes("document")
            ? "document"
            : r.capability.includes("url") || r.capability.includes("domain")
              ? "url"
              : r.capability.includes("data")
                ? "data"
                : "text",
      capability: r.capability,
      reason: r.reason,
    }))
  );

  // Capability-owned observations (live web inspection, source lists) must be
  // attached BEFORE discovery/finalization so the capability analyzer reads them.
  if (beforeDiscover) {
    const pending = (await getInvestigation(inv.id)) as Investigation;
    beforeDiscover(pending);
    await saveInvestigation(pending);
  }

  return discoverAndAcquire(inv.id, args.userId);
}