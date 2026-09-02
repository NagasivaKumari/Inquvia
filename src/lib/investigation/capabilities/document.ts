import type { Investigation, InvestigationInput } from "../../types";
import { runCapability, InputError } from "./shared";
import { planDocumentRequirements } from "../planner";
import type { CapabilityRunArgs } from "./types";

/**
 * DOCUMENT INVESTIGATION — atomic endpoint /api/x402/document-investigation.
 * Document analysis returning extracted findings, inconsistencies, and
 * evidence-backed confidence. The document (PDF/text) is extracted and passed
 * to the AI; planning targets document authenticity and source verification.
 */
export async function runDocumentInvestigation(
  args: CapabilityRunArgs
): Promise<Investigation> {
  const document = args.inputs.find((i) => i.type === "document");
  if (!document) throw new InputError("document-investigation requires a document file");

  const inputs: InvestigationInput[] = [document];
  const question = args.question.trim();

  return runCapability(
    "document-investigation",
    { ...args, inputs },
    planDocumentRequirements(question, ["document"]),
    "Document Investigation"
  );
}