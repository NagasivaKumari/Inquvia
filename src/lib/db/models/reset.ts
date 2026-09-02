import mongoose, { Schema, Document } from "mongoose";

export interface IReset extends Document {
  token: string;
  userId: string;
  createdAt: Date;
  expiresAt: Date;
  used: boolean;
}

const ResetSchema = new Schema(
  {
    token: { type: String, required: true, unique: true },
    userId: { type: String, ref: "User", required: true },
    createdAt: { type: Date, default: Date.now },
    expiresAt: { type: Date, required: true },
    used: { type: Boolean, default: false },
  },
  { timestamps: true }
);

export const Reset = mongoose.models.Reset || mongoose.model<IReset>("Reset", ResetSchema);
