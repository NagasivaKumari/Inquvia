import mongoose, { Schema, Document } from "mongoose";

export interface IPayment extends Document {
  userId?: string;
  investigationId?: string;
  capability?: string;
  payerAddress?: string;
  payToAddress?: string;
  amount?: number;
  currency?: string;
  network?: string;
  asset?: string;
  resourceUrl?: string;
  paymentMethod?: string;
  status?: string;
  requestId?: string;
  idempotencyKey?: string;
  x402?: {
    scheme: string;
    version: string;
    paymentRequirements: Record<string, any>;
    paymentHeaderReference: string;
  };
  transactionId?: string;
  settlementRef?: string;
  failureCode?: string;
  failureReason?: string;
  createdAt: Date;
  updatedAt: Date;
  settledAt?: Date;
}

const PaymentSchema = new Schema(
  {
    userId: { type: String, index: true },
    investigationId: { type: String, index: true },
    capability: { type: String },
    payerAddress: { type: String },
    payToAddress: { type: String },
    amount: { type: Number },
    currency: { type: String },
    network: { type: String },
    asset: String,
    resourceUrl: String,
    paymentMethod: { type: String, default: "x402" },
    status: { type: String, default: "settled" },
    requestId: String,
    idempotencyKey: { type: String },
    x402: {
      scheme: String,
      version: String,
      paymentRequirements: Schema.Types.Mixed,
      paymentHeaderReference: String,
    },
    transactionId: { type: String, index: true },
    settlementRef: String,
    failureCode: String,
    failureReason: String,
    settledAt: Date,
  },
  { timestamps: true }
);

PaymentSchema.index({ userId: 1, createdAt: -1 });

export const Payment =
  mongoose.models.Payment ||
  mongoose.model<IPayment>("Payment", PaymentSchema);
