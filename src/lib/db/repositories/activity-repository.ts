import { ActivityEvent, IActivityEvent } from "../models/activity-event";
import mongoose from "mongoose";

export class ActivityRepository {
  async listByInvestigation(investigationId: string, userId: string): Promise<IActivityEvent[]> {
    return await ActivityEvent.find({ investigationId, userId }).sort({ timestamp: -1 }).exec();
  }

  async create(eventData: Partial<IActivityEvent>): Promise<IActivityEvent> {
    const event = new ActivityEvent(eventData);
    return await event.save();
  }
}
