import type { InvestigationInput } from "../../types";

/**
 * Common arguments passed to every atomic capability handler by the shared
 * paid-route factory (after input parsing, storage and x402 payment gate).
 */
export interface CapabilityRunArgs {
  id: string;
  userId: string;
  question: string;
  inputs: InvestigationInput[];
  idempotencyKey?: string;
}