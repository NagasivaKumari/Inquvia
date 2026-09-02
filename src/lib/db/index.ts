import dbConnect from "./mongodb";
import { UserRepository } from "./repositories/user-repository";
import { InvestigationRepository } from "./repositories/investigation-repository";
import { PaymentRepository } from "./repositories/payment-repository";
import { WalletRepository } from "./repositories/wallet-repository";
import { ActivityRepository } from "./repositories/activity-repository";
import { EvidenceRepository } from "./repositories/evidence-repository";
import { CapabilityRepository } from "./repositories/capability-repository";
import { Session } from "./models/session";
import { Reset } from "./models/reset";
import { Investigation } from "./models/investigation";
import { Payment } from "./models/payment";
import type {
  Investigation as InvestigationType,
  PaymentRecord,
  PaymentPrefs,
  User,
  Session as SessionType,
} from "../types";

// Instances of repositories
const userRepo = new UserRepository();
const investigationRepo = new InvestigationRepository();
const paymentRepo = new PaymentRepository();
const walletRepo = new WalletRepository();
const activityRepo = new ActivityRepository();
const evidenceRepo = new EvidenceRepository();
const capabilityRepo = new CapabilityRepository();

// ── Users ──
export async function createUser(user: User): Promise<void> {
  await dbConnect();
  await userRepo.create(user as any);
}

export async function getUserById(id: string): Promise<User | null> {
  await dbConnect();
  const user = await userRepo.findById(id);
  return user ? (user.toObject() as User) : null;
}

export async function getUserByEmail(email: string): Promise<User | null> {
  await dbConnect();
  const user = await userRepo.findByEmail(email);
  return user ? (user.toObject() as User) : null;
}

export async function updateUser(id: string, updates: Partial<User>): Promise<User | null> {
  await dbConnect();
  const user = await userRepo.update(id, updates as any);
  return user ? (user.toObject() as User) : null;
}

export async function updateUserPrefs(id: string, prefs: PaymentPrefs): Promise<User | null> {
  return updateUser(id, { paymentPrefs: prefs });
}

// ── Investigations ──
export async function saveInvestigation(inv: InvestigationType): Promise<void> {
  await dbConnect();
  const exists = await investigationRepo.exists(inv.id, inv.userId || "");
  if (exists) {
    await investigationRepo.update(inv.id, inv.userId || "", inv as any);
  } else {
    await investigationRepo.create(inv as any);
  }
}

export async function getInvestigation(id: string): Promise<InvestigationType | null> {
  await dbConnect();
  // Note: This legacy function doesn't take userId, which is a security risk.
  // We'll have to find a way to make it work or update calling code.
  const inv = await Investigation.findById(id).exec();
  return inv ? (inv.toObject() as InvestigationType) : null;
}

export async function listInvestigations(limit = 50, userId?: string): Promise<InvestigationType[]> {
  await dbConnect();
  if (!userId) return [];
  const invs = await investigationRepo.list(userId, limit);
  return invs.map(i => i.toObject() as InvestigationType);
}

// ── Payments ──
/** Map a Mongoose Payment doc to the domain PaymentRecord (string ids). */
function toPaymentRecord(p: any): PaymentRecord {
  return {
    id: String(p._id ?? p.id ?? ""),
    investigationId: String(p.investigationId ?? ""),
    providerId: p.providerId ?? p.capability ?? "unknown",
    capability: p.capability,
    amount: p.amount,
    currency: p.currency,
    network: p.network,
    protocol: p.paymentMethod ?? "x402",
    status: p.status as PaymentRecord["status"],
    settlementRef: p.transactionId ?? p.settlementRef,
    timestamp: (p.createdAt ?? new Date()).toISOString(),
  };
}

export async function savePayment(rec: PaymentRecord): Promise<void> {
  await dbConnect();
  await Payment.create({
    userId: rec.userId,
    investigationId: rec.investigationId,
    capability: rec.capability,
    amount: rec.amount,
    currency: rec.currency,
    network: rec.network,
    paymentMethod: rec.protocol,
    status: rec.status,
    transactionId: rec.settlementRef,
    settlementRef: rec.settlementRef,
  } as any);
}

export async function listPayments(limit = 10000): Promise<PaymentRecord[]> {
  await dbConnect();
  const docs = await Payment.find().sort({ createdAt: -1 }).limit(limit).exec();
  return docs.map(d => toPaymentRecord(d));
}

export async function getUserPayments(userId: string): Promise<PaymentRecord[]> {
  await dbConnect();
  const docs = await Payment.find({ userId }).sort({ createdAt: -1 }).exec();
  return docs.map(d => toPaymentRecord(d));
}

export async function getPaymentsForInvestigation(investigationId: string): Promise<PaymentRecord[]> {
  await dbConnect();
  const docs = await Payment.find({ investigationId }).sort({ createdAt: -1 }).exec();
  return docs.map(d => toPaymentRecord(d));
}

export async function getInvestigationByIdempotencyKey(
  idempotencyKey: string,
  userId: string
): Promise<InvestigationType | null> {
  await dbConnect();
  const inv = await Investigation.findOne({ idempotencyKey, userId }).exec();
  return inv ? (inv.toObject() as InvestigationType) : null;
}

// ── Sessions & Resets ──
export async function createSession(session: SessionType): Promise<void> {
  await dbConnect();
  await Session.create(session);
}

export async function getSession(id: string): Promise<SessionType | null> {
  await dbConnect();
  const session = await Session.findOne({ id }).exec();
  return session ? (session.toObject() as SessionType) : null;
}

export async function deleteSession(id: string): Promise<void> {
  await dbConnect();
  await Session.deleteOne({ id }).exec();
}

export async function deleteExpiredSessions(): Promise<void> {
  await dbConnect();
  await Session.deleteMany({ expiresAt: { $lt: new Date() } }).exec();
}

export async function createReset(token: string, userId: string): Promise<void> {
  await dbConnect();
  await Reset.create({
    token,
    userId,
    createdAt: new Date(),
    expiresAt: new Date(Date.now() + 1000 * 60 * 60),
    used: false,
  });
}

export async function getReset(token: string): Promise<any | null> {
  await dbConnect();
  return await Reset.findOne({ token }).exec();
}

export async function markResetUsed(token: string): Promise<void> {
  await dbConnect();
  await Reset.updateOne({ token }, { used: true }).exec();
}

// ── Stats ──
export async function getDashboardStats(userId?: string): Promise<any> {
  await dbConnect();
  // Implement using Mongoose aggregation on Investigation and Payment collections
  return {
    totalInvestigations: 0,
    investigationsThisWeek: 0,
    evidenceChecksPurchased: 0,
    totalSpend: 0,
    averageConfidence: 0,
    casesByType: {},
  };
}
