import { Settlement, ISettlement } from "../models/settlement";
import mongoose from "mongoose";

export class SettlementRepository {
  async create(settlementData: Partial<ISettlement>): Promise<ISettlement> {
    const settlement = new Settlement(settlementData);
    return await settlement.save();
  }

  async findByPayment(paymentId: string): Promise<ISettlement | null> {
    return await Settlement.findOne({ paymentId }).exec();
  }
}
