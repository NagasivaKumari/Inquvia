import mongoose, { Schema, Document } from "mongoose";

export interface IInvestigation extends Document {
  id: string;
  userId: string;
  capability: string;
  endpoint: string;
  idempotencyKey?: string;
  question: string;
  inputs: Array<{
    type: string;
    value?: string;
    fileId?: string;
    metadata?: Record<string, any>;
  }>;
  status: string;
  investigationPlan: Array<{
    requirementId: string;
    type: string;
    description: string;
    reason: string;
    status: string;
    estimatedCost: number;
  }>;
  confidence?: number;
  conclusion?: string;
  risk?: string;
  summary?: string;
  limitations?: string[];
  budget: {
    maxPerCheck: number;
    maxPerInvestigation: number;
    sessionBudget: number;
  };
  economicSummary: {
    estimatedCost: number;
    totalSpent: number;
    checksRequested: number;
    checksCompleted: number;
  };
  startedAt?: Date;
  completedAt?: Date;
  createdAt: Date;
  updatedAt: Date;
}

const InvestigationSchema = new Schema(
  {
    id: { type: String, required: true, unique: true },
    userId: { type: String, required: true, index: true },
    capability: { type: String, required: true },
    endpoint: { type: String, required: true },
    idempotencyKey: { type: String, index: true },
    question: { type: String, required: true },
    inputs: [
      {
        type: { type: String, required: true },
        value: String,
        fileId: String,
        metadata: Schema.Types.Mixed,
      },
    ],
    status: { type: String, required: true, index: true },
    investigationPlan: [
      {
        requirementId: String,
        type: String,
        description: String,
        reason: String,
        status: String,
        estimatedCost: Number,
      },
    ],
    confidence: Number,
    conclusion: String,
    risk: String,
    summary: String,
    limitations: [String],
    budget: {
      maxPerCheck: Number,
      maxPerInvestigation: Number,
      sessionBudget: Number,
    },
    economicSummary: {
      estimatedCost: Number,
      totalSpent: Number,
      checksRequested: Number,
      checksCompleted: Number,
    },
    startedAt: Date,
    completedAt: Date,
  },
  { timestamps: true }
);

// Indexes
InvestigationSchema.index({ userId: 1, createdAt: -1 });
InvestigationSchema.index({ userId: 1, status: 1 });

export const Investigation =
  mongoose.models.Investigation || mongoose.model<IInvestigation>("Investigation", InvestigationSchema);
