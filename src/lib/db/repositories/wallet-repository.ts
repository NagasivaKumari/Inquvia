import { Wallet, IWallet } from "../models/wallet";
import mongoose from "mongoose";

export class WalletRepository {
  async findByUser(userId: string): Promise<IWallet[]> {
    return await Wallet.find({ userId }).exec();
  }

  async findByAddress(address: string, network: string): Promise<IWallet | null> {
    return await Wallet.findOne({ address, network }).exec();
  }

  async create(walletData: Partial<IWallet>): Promise<IWallet> {
    const wallet = new Wallet(walletData);
    return await wallet.save();
  }
}
