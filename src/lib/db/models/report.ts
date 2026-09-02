import mongoose, { Schema, Document } from "mongoose";

export interface IReport extends Document {
  userId: string;
  investigationId: string;
  title: string;
  summary: string;
  conclusion: string;
  confidence: number;
  risk: string;
  findings: any[];
  supportingEvidenceIds: string[];
  contradictoryEvidenceIds: string[];
  uncertainEvidenceIds: string[];
  limitations: string[];
  economicSummary: {
    checksPurchased: number;
    totalSpent: number;
    currency: string;
  };
  settlementReferences: string[];
  createdAt: Date;
  updatedAt: Date;
}

const ReportSchema = new Schema(
  {
    userId: { type: String, ref: "User", required: true, index: true },
    investigationId: { type: String, ref: "Investigation", required: true, index: true },
    title: { type: String, required: true },
    summary: String,
    conclusion: String,
    confidence: Number,
    risk: String,
    findings: [Schema.Types.Mixed],
    supportingEvidenceIds: [{ type: String, ref: "Evidence" }],
    contradictoryEvidenceIds: [{ type: String, ref: "Evidence" }],
    uncertainEvidenceIds: [{ type: String, ref: "Evidence" }],
    limitations: [String],
    economicSummary: {
      checksPurchased: Number,
      totalSpent: Number,
      currency: String,
    },
    settlementReferences: [{ type: String, ref: "Settlement" }],
  },
  { timestamps: true }
);

ReportSchema.index({ userId: 1, createdAt: -1 });

export const Report =
  mongoose.models.Report ||
  mongoose.model<IReport>("Report", ReportSchema);
