import mongoose, { Schema, Document } from "mongoose";

export interface IProviderService extends Document {
  externalId: string;
  name: string;
  description?: string;
  endpoint: string;
  capabilities: string[];
  inputTypes: string[];
  price: number;
  currency: string;
  network: string;
  asset: string;
  paymentRequirements?: Record<string, any>;
  discoverySource: string;
  available: boolean;
  lastDiscoveredAt: Date;
  metadata?: Record<string, any>;
  createdAt: Date;
  updatedAt: Date;
}

const ProviderServiceSchema = new Schema(
  {
    externalId: { type: String, required: true, unique: true, index: true },
    name: { type: String, required: true },
    description: String,
    endpoint: { type: String, required: true },
    capabilities: [String],
    inputTypes: [String],
    price: { type: Number, required: true },
    currency: { type: String, required: true },
    network: { type: String, required: true },
    asset: String,
    paymentRequirements: Schema.Types.Mixed,
    discoverySource: { type: String, required: true },
    available: { type: Boolean, default: true, index: true },
    lastDiscoveredAt: { type: Date, default: Date.now },
    metadata: Schema.Types.Mixed,
  },
  { timestamps: true }
);

export const ProviderService =
  mongoose.models.ProviderService ||
  mongoose.model<IProviderService>("ProviderService", ProviderServiceSchema);
