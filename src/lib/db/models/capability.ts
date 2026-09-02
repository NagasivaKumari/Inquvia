import mongoose, { Schema, Document } from "mongoose";

export interface ICapability extends Document {
  slug: string;
  name: string;
  description: string;
  endpoint: string;
  inputTypes: string[];
  price: number;
  currency: string;
  network: string;
  asset: string;
  payTo: string;
  challengeTag: string;
  active: boolean;
  discoveryEnabled: boolean;
  createdAt: Date;
  updatedAt: Date;
}

const CapabilitySchema = new Schema(
  {
    slug: { type: String, required: true, unique: true, index: true },
    name: { type: String, required: true },
    description: String,
    endpoint: { type: String, required: true },
    inputTypes: [String],
    price: { type: Number, required: true },
    currency: { type: String, required: true },
    network: { type: String, required: true },
    asset: String,
    payTo: { type: String, required: true },
    challengeTag: { type: String, required: true },
    active: { type: Boolean, default: true, index: true },
    discoveryEnabled: { type: Boolean, default: true },
  },
  { timestamps: true }
);

export const Capability =
  mongoose.models.Capability ||
  mongoose.model<ICapability>("Capability", CapabilitySchema);
