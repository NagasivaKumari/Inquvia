import { Report, IReport } from "../models/report";
import mongoose from "mongoose";

export class ReportRepository {
  async findByInvestigation(investigationId: string, userId: string): Promise<IReport | null> {
    return await Report.findOne({ investigationId, userId }).exec();
  }

  async create(reportData: Partial<IReport>): Promise<IReport> {
    const report = new Report(reportData);
    return await report.save();
  }
}
