import type { Investigation, InvestigationInput } from "../../types";
import { runCapability, InputError } from "./shared";
import { planImageRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

/**
 * IMAGE INVESTIGATION — atomic endpoint /api/x402/image-investigation.
 * Image analysis returning authenticity/context findings and evidence-backed
 * confidence. The submitted image file is analyzed directly (multimodal AI
 * when available) and planning targets provenance, prior occurrences, and
 * metadata integrity.
 */
export async function runImageInvestigation(
  args: CapabilityRunArgs
): Promise<Investigation> {
  const image = args.inputs.find((i) => i.type === "image");
  if (!image) throw new InputError("image-investigation requires an image file");

  const inputs: InvestigationInput[] = [image];
  const question = args.question.trim();

  return runCapability(
    "image-investigation",
    { ...args, inputs },
    planImageRequirements(question, ["image"]),
    "Image Investigation"
  );
}