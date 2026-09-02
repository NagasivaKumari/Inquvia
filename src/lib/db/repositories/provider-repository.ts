import { ProviderService, IProviderService } from "../models/provider-service";

export class ProviderRepository {
  async listAvailable(): Promise<IProviderService[]> {
    return await ProviderService.find({ available: true }).exec();
  }

  async findByExternalId(externalId: string): Promise<IProviderService | null> {
    return await ProviderService.findOne({ externalId }).exec();
  }

  async createOrUpdate(externalId: string, data: Partial<IProviderService>): Promise<IProviderService | null> {
    return await ProviderService.findOneAndUpdate({ externalId }, { ...data, updatedAt: new Date() }, { upsert: true, new: true }).exec();
  }
}
