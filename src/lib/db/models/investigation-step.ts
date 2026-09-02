import mongoose, { Schema, Document } from "mongoose";

export interface IInvestigationStep extends Document {
  investigationId: string;
  type: string;
  name: string;
  status: string;
  sequence: number;
  startedAt?: Date;
  completedAt?: Date;
  errorCode?: string;
  errorMessage?: string;
  metadata?: Record<string, any>;
  createdAt: Date;
  updatedAt: Date;
}

const InvestigationStepSchema = new Schema(
  {
    investigationId: { type: String, ref: "Investigation", required: true, index: true },
    type: { type: String, required: true },
    name: { type: String, required: true },
    status: { type: String, required: true },
    sequence: { type: Number, required: true },
    startedAt: Date,
    completedAt: Date,
    errorCode: String,
    errorMessage: String,
    metadata: Schema.Types.Mixed,
  },
  { timestamps: true }
);

InvestigationStepSchema.index({ investigationId: 1, sequence: 1 });
InvestigationStepSchema.index({ investigationId: 1, createdAt: 1 });

export const InvestigationStep =
  mongoose.models.InvestigationStep ||
  mongoose.model<IInvestigationStep>("InvestigationStep", InvestigationStepSchema);
