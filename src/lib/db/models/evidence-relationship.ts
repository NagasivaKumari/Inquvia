import mongoose, { Schema, Document } from "mongoose";

export interface IEvidenceRelationship extends Document {
  investigationId: string;
  fromType: string;
  fromId: string;
  relationship: string;
  toType: string;
  toId: string;
  confidence: number;
  createdAt: Date;
}

const EvidenceRelationshipSchema = new Schema(
  {
    investigationId: { type: String, ref: "Investigation", required: true, index: true },
    fromType: { type: String, required: true },
    fromId: { type: String, required: true },
    relationship: { type: String, required: true },
    toType: { type: String, required: true },
    toId: { type: String, required: true },
    confidence: { type: Number, required: true },
  },
  { timestamps: true }
);

EvidenceRelationshipSchema.index({ investigationId: 1 });

export const EvidenceRelationship =
  mongoose.models.EvidenceRelationship ||
  mongoose.model<IEvidenceRelationship>("EvidenceRelationship", EvidenceRelationshipSchema);
