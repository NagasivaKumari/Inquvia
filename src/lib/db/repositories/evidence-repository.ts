import { Evidence, IEvidence } from "../models/evidence";
import mongoose from "mongoose";

export class EvidenceRepository {
  async findByInvestigation(investigationId: string): Promise<IEvidence[]> {
    return await Evidence.find({ investigationId }).exec();
  }

  async create(evidenceData: Partial<IEvidence>): Promise<IEvidence> {
    const evidence = new Evidence(evidenceData);
    return await evidence.save();
  }
}
