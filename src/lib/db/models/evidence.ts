import mongoose, { Schema, Document } from "mongoose";

export interface IEvidence extends Document {
  investigationId: string;
  type: string;
  source: {
    name: string;
    url: string;
    publisher: string;
  };
  provider: {
    serviceId: string;
    name: string;
    endpoint: string;
  };
  contentReference: string;
  finding: string;
  relationship: string;
  confidence: number;
  supportsClaim: boolean;
  contradictsClaim: boolean;
  verificationStatus: string;
  acquisition: {
    paymentId?: string;
    settlementId?: string;
    cost: number;
    currency: string;
    network: string;
    acquiredAt: Date;
  };
  metadata?: Record<string, any>;
  createdAt: Date;
  updatedAt: Date;
}

const EvidenceSchema = new Schema(
  {
    investigationId: { type: String, ref: "Investigation", required: true, index: true },
    type: { type: String, required: true },
    source: {
      name: String,
      url: String,
      publisher: String,
    },
    provider: {
      serviceId: String,
      name: String,
      endpoint: String,
    },
    contentReference: String,
    finding: String,
    relationship: String,
    confidence: Number,
    supportsClaim: Boolean,
    contradictsClaim: Boolean,
    verificationStatus: String,
    acquisition: {
      paymentId: { type: String, ref: "Payment" },
      settlementId: { type: String, ref: "Settlement" },
      cost: Number,
      currency: String,
      network: String,
      acquiredAt: Date,
    },
    metadata: Schema.Types.Mixed,
  },
  { timestamps: true }
);

EvidenceSchema.index({ investigationId: 1, createdAt: -1 });
EvidenceSchema.index({ investigationId: 1, type: 1 });

export const Evidence =
  mongoose.models.Evidence || mongoose.model<IEvidence>("Evidence", EvidenceSchema);
