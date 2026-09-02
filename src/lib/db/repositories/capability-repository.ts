import { Capability, ICapability } from "../models/capability";

export class CapabilityRepository {
  async findAllActive(): Promise<ICapability[]> {
    return await Capability.find({ active: true }).exec();
  }

  async findBySlug(slug: string): Promise<ICapability | null> {
    return await Capability.findOne({ slug, active: true }).exec();
  }
}
