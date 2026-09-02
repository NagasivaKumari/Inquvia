import mongoose, { Schema, Document } from "mongoose";

export interface ISession extends Document {
  id: string;
  userId: string;
  createdAt: Date;
  expiresAt: Date;
}

const SessionSchema = new Schema(
  {
    id: { type: String, required: true, unique: true },
    userId: { type: String, ref: "User", required: true },
    createdAt: { type: Date, default: Date.now },
    expiresAt: { type: Date, required: true },
  },
  { timestamps: true }
);

SessionSchema.index({ expiresAt: 1 }, { expireAfterSeconds: 0 });

export const Session = mongoose.models.Session || mongoose.model<ISession>("Session", SessionSchema);
