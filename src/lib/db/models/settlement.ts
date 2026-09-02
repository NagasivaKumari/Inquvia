import mongoose, { Schema, Document } from "mongoose";

export interface ISettlement extends Document {
  paymentId: string;
  network: string;
  asset: string;
  txId: string;
  payer: string;
  receiver: string;
  amount: number;
  facilitator: string;
  status: string;
  confirmedAt?: Date;
  explorerUrl?: string;
  rawReference?: Record<string, any>;
  createdAt: Date;
}

const SettlementSchema = new Schema(
  {
    paymentId: { type: String, ref: "Payment", required: true, index: true },
    network: { type: String, required: true },
    asset: { type: String, required: true },
    txId: { type: String, required: true, unique: true },
    payer: { type: String, required: true },
    receiver: { type: String, required: true },
    amount: { type: Number, required: true },
    facilitator: { type: String, required: true },
    status: { type: String, required: true },
    confirmedAt: Date,
    explorerUrl: String,
    rawReference: Schema.Types.Mixed,
  },
  { timestamps: true }
);

export const Settlement =
  mongoose.models.Settlement ||
  mongoose.model<ISettlement>("Settlement", SettlementSchema);
