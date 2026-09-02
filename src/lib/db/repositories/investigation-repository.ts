import { Investigation, IInvestigation } from "../models/investigation";
import mongoose from "mongoose";

export class InvestigationRepository {
  async create(investigationData: Partial<IInvestigation>): Promise<IInvestigation> {
    const investigation = new Investigation(investigationData);
    return await investigation.save();
  }

  async findById(id: string, userId: string): Promise<IInvestigation | null> {
    return await Investigation.findOne({ id, userId }).exec();
  }

  async list(userId: string, limit: number = 50): Promise<IInvestigation[]> {
    return await Investigation.find({ userId })
      .sort({ createdAt: -1 })
      .limit(limit)
      .exec();
  }

  async update(id: string, userId: string, updates: Partial<IInvestigation>): Promise<IInvestigation | null> {
    return await Investigation.findOneAndUpdate(
      { id, userId },
      { ...updates, updatedAt: new Date() },
      { new: true }
    ).exec();
  }

  async exists(id: string, userId: string): Promise<boolean> {
    const count = await Investigation.countDocuments({ id, userId }).exec();
    return count > 0;
  }
}
