import type { Investigation, InvestigationInput } from "../../types";
import { runCapability, InputError } from "./shared";
import { planVideoRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

/**
 * VIDEO INVESTIGATION — atomic endpoint /api/x402/video-investigation.
 * Video analysis returning contextual/evidence-backed findings for a submitted
 * video. The video file is analyzed directly when the AI provider can consume
 * it; planning targets video analysis, frame evidence, and metadata.
 */
export async function runVideoInvestigation(
  args: CapabilityRunArgs
): Promise<Investigation> {
  const video = args.inputs.find((i) => i.type === "video");
  if (!video) throw new InputError("video-investigation requires a video file");

  const inputs: InvestigationInput[] = [video];
  const question = args.question.trim();

  return runCapability(
    "video-investigation",
    { ...args, inputs },
    planVideoRequirements(question, ["video"]),
    "Video Investigation"
  );
}