import { Payment, IPayment } from "../models/payment";
import mongoose from "mongoose";

export class PaymentRepository {
  async findById(id: string, userId: string): Promise<IPayment | null> {
    return await Payment.findOne({ _id: id, userId }).exec();
  }

  async create(paymentData: Partial<IPayment>): Promise<IPayment> {
    const payment = new Payment(paymentData);
    return await payment.save();
  }

  async updateStatus(id: string, status: string, updates: Partial<IPayment>): Promise<IPayment | null> {
    return await Payment.findByIdAndUpdate(id, { status, ...updates, updatedAt: new Date() }, { new: true }).exec();
  }
}
