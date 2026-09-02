import { User, IUser } from "../models/user";
import mongoose from "mongoose";

export class UserRepository {
  async findById(id: string): Promise<IUser | null> {
    return await User.findOne({ id }).exec();
  }

  async findByEmail(email: string): Promise<IUser | null> {
    return await User.findOne({ email: email.toLowerCase() }).exec();
  }

  async create(userData: Partial<IUser>): Promise<IUser> {
    const user = new User(userData);
    return await user.save();
  }

  async update(id: string, updates: Partial<IUser>): Promise<IUser | null> {
    return await User.findOneAndUpdate({ id }, { ...updates, updatedAt: new Date() }, { new: true }).exec();
  }
}
