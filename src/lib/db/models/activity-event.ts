import mongoose, { Schema, Document } from "mongoose";

export interface IActivityEvent extends Document {
  userId: string;
  investigationId?: string;
  paymentId?: string;
  type: string;
  message: string;
  metadata?: Record<string, any>;
  timestamp: Date;
}

const ActivityEventSchema = new Schema(
  {
    userId: { type: String, ref: "User", required: true, index: true },
    investigationId: { type: String, ref: "Investigation", index: true },
    paymentId: { type: String, ref: "Payment" },
    type: { type: String, required: true },
    message: { type: String, required: true },
    metadata: Schema.Types.Mixed,
    timestamp: { type: Date, default: Date.now, index: true },
  },
  { timestamps: true }
);

export const ActivityEvent =
  mongoose.models.ActivityEvent ||
  mongoose.model<IActivityEvent>("ActivityEvent", ActivityEventSchema);
