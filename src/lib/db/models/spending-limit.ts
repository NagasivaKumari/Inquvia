import mongoose, { Schema, Document } from "mongoose";

export interface ISpendingLimit extends Document {
  userId: string;
  maxPerEvidenceCheck: number;
  maxPerInvestigation: number;
  sessionBudget: number;
  sessionSpent: number;
  updatedAt: Date;
}

const SpendingLimitSchema = new Schema(
  {
    userId: { type: String, ref: "User", required: true, unique: true },
    maxPerEvidenceCheck: { type: Number, required: true },
    maxPerInvestigation: { type: Number, required: true },
    sessionBudget: { type: Number, required: true },
    sessionSpent: { type: Number, default: 0 },
  },
  { timestamps: true }
);

export const SpendingLimit =
  mongoose.models.SpendingLimit ||
  mongoose.model<ISpendingLimit>("SpendingLimit", SpendingLimitSchema);
