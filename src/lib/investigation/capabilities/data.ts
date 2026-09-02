import type { Investigation, InvestigationInput } from "../../types";
import { runCapability, InputError } from "./shared";
import { planDataRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

/**
 * DATA INVESTIGATION — atomic endpoint /api/x402/data-investigation.
 * Structured-data analysis returning detected anomalies, supporting analysis,
 * and confidence. Only implemented when a real, meaningful structured-data
 * capability exists: the CSV/JSON dataset is extracted and analyzed for
 * inconsistency/outlier signals.
 */
export async function runDataInvestigation(
  args: CapabilityRunArgs
): Promise<Investigation> {
  const data = args.inputs.find(
    (i) =>
      i.type === "data" ||
      (i.mimeType &&
        (i.mimeType.includes("csv") ||
          i.mimeType.includes("json")))
  );
  if (!data) {
    throw new InputError("data-investigation requires a CSV/JSON dataset file");
  }

  const inputs: InvestigationInput[] = [data];
  const question = args.question.trim();

  return runCapability(
    "data-investigation",
    { ...args, inputs },
    planDataRequirements(question, ["data"]),
    "Data Investigation"
  );
}