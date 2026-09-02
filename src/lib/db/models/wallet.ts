import mongoose, { Schema, Document } from "mongoose";

export interface IWallet extends Document {
  userId: string;
  address: string;
  network: string;
  walletProvider: string;
  isPrimary: boolean;
  connectedAt: Date;
  disconnectedAt?: Date;
  createdAt: Date;
  updatedAt: Date;
}

const WalletSchema = new Schema(
  {
    userId: { type: String, ref: "User", required: true, index: true },
    address: { type: String, required: true, index: true },
    network: { type: String, required: true },
    walletProvider: { type: String, required: true },
    isPrimary: { type: Boolean, default: false },
    connectedAt: { type: Date, default: Date.now },
    disconnectedAt: { type: Date },
  },
  { timestamps: true }
);

// Compound index for userId + address uniqueness per network
WalletSchema.index({ userId: 1, address: 1, network: 1 }, { unique: true });

export const Wallet = mongoose.models.Wallet || mongoose.model<IWallet>("Wallet", WalletSchema);
