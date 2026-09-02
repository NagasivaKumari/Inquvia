import type { Investigation, InvestigationInput } from "../../types";
import { runCapability, InputError } from "./shared";
import { planSourceRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

/**
 * SOURCE INVESTIGATION — atomic endpoint /api/x402/source-investigation.
 * Source analysis evaluating a submitted URL and returning source/context
 * findings. Performs a live web inspection (DNS/SSL/HTTP/content) recorded on
 * the investigation; planning targets domain, SSL, and content telemetry.
 */
export async function runSourceInvestigation(
  args: CapabilityRunArgs
): Promise<Investigation> {
  const urlInput = args.inputs.find((i) => i.type === "url");
  if (!urlInput?.content) {
    throw new InputError("source-investigation requires a valid URL");
  }

  const inputs: InvestigationInput[] = [{ type: "url", content: urlInput.content }];
  const question = args.question.trim() || `Analyze the source: ${urlInput.content}`;

  // Live web inspection is the source capability's distinct evidence pipeline.
  // It runs BEFORE discovery so the analyzer reads it during finalization.
  const { inspectLiveUrl } = await import("../webInspector");
  const inspection = await inspectLiveUrl(urlInput.content);

  const inv = await runCapability(
    "source-investigation",
    { ...args, inputs },
    planSourceRequirements(question, ["url"]),
    "Source Investigation",
    (pending) => {
      if (!inspection) return;
      (pending as unknown as { webInspection: unknown }).webInspection = inspection;
      pending.sourcesUsed = [urlInput.content, ...(pending.sourcesUsed ?? [])];
    }
  );
  return inv;
}