import { SpendingLimit, ISpendingLimit } from "../models/spending-limit";

export class SpendingLimitRepository {
  async findByUser(userId: string): Promise<ISpendingLimit | null> {
    return await SpendingLimit.findOne({ userId }).exec();
  }

  async update(userId: string, updates: Partial<ISpendingLimit>): Promise<ISpendingLimit | null> {
    return await SpendingLimit.findOneAndUpdate({ userId }, { ...updates, updatedAt: new Date() }, { new: true, upsert: true }).exec();
  }
}
