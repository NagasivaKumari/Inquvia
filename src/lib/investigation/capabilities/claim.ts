import type { Investigation, InvestigationInput } from "../../types";
import { runCapability } from "./shared";
import { planClaimRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

export interface ClaimRunArgs extends CapabilityRunArgs {
  /** Optional supporting context accompanying the claim. */
  context?: string;
}

/**
 * CLAIM INVESTIGATION — atomic endpoint /api/x402/claim-investigation.
 * Evidence-backed analysis of a submitted claim with supporting,
 * contradictory, and uncertain findings. Planning targets original-source
 * location, supporting evidence, independent corroboration, and contradictory
 * evidence. The claim+context (text) is the required input.
 */
export async function runClaimInvestigation(
  args: ClaimRunArgs
): Promise<Investigation> {
  const claim: InvestigationInput =
    args.context?.trim()
      ? { type: "text", content: args.context.trim() }
      : args.inputs.find((i) => i.type === "text") ?? {
          type: "text",
          content: args.question,
        };
  const inputs = [claim, ...args.inputs.filter((i) => i !== claim)];

  return runCapability(
    "claim-investigation",
    { ...args, inputs },
    planClaimRequirements(args.question, inputs.map((i) => i.type)),
    "Claim Investigation"
  );
}