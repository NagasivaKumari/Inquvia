import mongoose, { Schema, Document } from "mongoose";

export interface IUser extends Document {
  id: string;
  name: string;
  email: string;
  passwordHash: string;
  authProviders: {
    email: boolean;
    wallet: boolean;
  };
  status: string;
  createdAt: Date;
  updatedAt: Date;
  lastLoginAt?: Date;
  walletAddress?: string;
  walletNetwork?: string;
  paymentPrefs?: {
    maxPerEvidenceCheck: number;
    maxPerInvestigation: number;
    sessionBudget: number;
    totalBudget: number;
  };
}

const UserSchema = new Schema(
  {
    id: { type: String, required: true, unique: true },
    name: { type: String, required: true },
    email: { type: String, required: true, unique: true, lowercase: true, trim: true },
    passwordHash: { type: String, required: true },
    authProviders: {
      email: { type: Boolean, default: true },
      wallet: { type: Boolean, default: false },
    },
    status: { type: String, default: "active" },
    lastLoginAt: { type: Date },
    walletAddress: { type: String },
    walletNetwork: { type: String },
    paymentPrefs: {
      maxPerEvidenceCheck: { type: Number, default: 0.01 },
      maxPerInvestigation: { type: Number, default: 0.5 },
      sessionBudget: { type: Number, default: 5 },
      totalBudget: { type: Number, default: 50 },
    },
  },
  { timestamps: true }
);

export const User = mongoose.models.User || mongoose.model<IUser>("User", UserSchema);
