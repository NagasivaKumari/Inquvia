import { cookies } from "next/headers";
import bcrypt from "bcryptjs";
import { nanoid } from "nanoid";
import {
  createUser,
  createSession,
  getSession,
  getUserById,
  getUserByEmail,
  deleteSession,
  deleteExpiredSessions,
  createReset,
  getReset,
  markResetUsed,
  updateUser,
  getInvestigation,
} from "../db";
import type { Session, User } from "../types";
import { DEFAULT_PAYMENT_PREFS } from "../types";

export const SESSION_COOKIE = "inquvia_session";

export const SESSION_DURATION_MS = 1000 * 60 * 60 * 24 * 30; // 30 days

export type AuthResult<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string };

/** Public-safe view of a user (never exposes passwordHash). */
export function toPublicUser(user: User): Omit<User, "passwordHash"> {
  const { passwordHash: _ph, ...rest } = user;
  return rest;
}

export function hashPassword(password: string): string {
  return bcrypt.hashSync(password, 10);
}

export function verifyPassword(password: string, hash: string): boolean {
  return bcrypt.compareSync(password, hash);
}

export async function signup(input: {
  name: string;
  email: string;
  password: string;
}): Promise<AuthResult<Omit<User, "passwordHash">>> {
  const email = input.email.trim().toLowerCase();
  const name = input.name.trim();
  const password = input.password;

  if (!name || name.length < 2) {
    return { ok: false, error: "Please enter your name." };
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return { ok: false, error: "Please enter a valid email address." };
  }
  if (password.length < 8) {
    return { ok: false, error: "Password must be at least 8 characters." };
  }
  if (await getUserByEmail(email)) {
    return { ok: false, error: "An account with this email already exists." };
  }

  const user: User = {
    id: `usr_${nanoid(12)}`,
    name,
    email,
    passwordHash: hashPassword(password),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    paymentPrefs: { ...DEFAULT_PAYMENT_PREFS },
  };
  await createUser(user);
  return { ok: true, data: toPublicUser(user) };
}

export async function login(input: {
  email: string;
  password: string;
  remember?: boolean;
}): Promise<AuthResult<User>> {
  const email = input.email.trim().toLowerCase();
  const user = await getUserByEmail(email);
  if (!user || !verifyPassword(input.password, user.passwordHash)) {
    return { ok: false, error: "Invalid email or password." };
  }
  return { ok: true, data: user };
}

export async function createUserSession(
  userId: string,
  remember: boolean
): Promise<Session> {
  await deleteExpiredSessions();
  const now = Date.now();
  const duration = remember
    ? SESSION_DURATION_MS
    : 1000 * 60 * 60 * 4; // 4h if not remembered
  const session: Session = {
    id: `ses_${nanoid(20)}`,
    userId,
    createdAt: new Date(now).toISOString(),
    expiresAt: new Date(now + duration).toISOString(),
  };
  await createSession(session);
  return session;
}

/** Returns the currently authenticated user, or null. */
export async function getCurrentUser(): Promise<User | null> {
  const store = await cookies();
  const sessionId = store.get(SESSION_COOKIE)?.value;
  if (!sessionId) return null;
  const session = await getSession(sessionId);
  if (!session) return null;
  if (new Date(session.expiresAt).getTime() < Date.now()) {
    await deleteSession(sessionId);
    return null;
  }
  return getUserById(session.userId);
}

export async function requireUser(): Promise<User> {
  const user = await getCurrentUser();
  if (!user) {
    throw new Error("UNAUTHORIZED");
  }
  return user;
}

/**
 * Ownership check: returns true only if the investigation exists and belongs
 * to the given user.
 */
export async function ownsInvestigation(investigationId: string, userId?: string): Promise<boolean> {
  const inv = await getInvestigation(investigationId);
  if (!inv) return false;
  if (!userId) return false;
  return inv.userId === userId;
}

export async function logout(): Promise<void> {
  const store = await cookies();
  const sessionId = store.get(SESSION_COOKIE)?.value;
  if (sessionId) await deleteSession(sessionId);
  store.delete(SESSION_COOKIE);
}

/** Creates a password reset token for an existing email. Returns public info only.
 * Never reveals whether an account exists — always returns ok so callers can show
 * a generic message. Tokens are only issued for real accounts. */
export async function requestPasswordReset(
  email: string
): Promise<AuthResult<{ token: string }>> {
  const user = await getUserByEmail(email.trim().toLowerCase());
  if (!user) {
    return { ok: true, data: { token: "" } };
  }
  const token = nanoid(40);
  await createReset(token, user.id);
  return { ok: true, data: { token } };
}

/** Checks whether a reset token is valid (exists, unused, not expired). */
export async function isValidResetToken(token: string): Promise<boolean> {
  if (!token) return false;
  const reset = await getReset(token);
  if (!reset || reset.used) return false;
  if (new Date(reset.expiresAt).getTime() < Date.now()) return false;
  return true;
}

/** Resets a password using a valid, unused reset token. */
export async function resetPassword(
  token: string,
  newPassword: string
): Promise<AuthResult<null>> {
  if (!token || newPassword.length < 8) {
    return { ok: false, error: "Password must be at least 8 characters." };
  }
  const reset = await getReset(token);
  if (!reset || reset.used || new Date(reset.expiresAt).getTime() < Date.now()) {
    return { ok: false, error: "This reset link is invalid or has expired." };
  }
  const user = await getUserById(reset.userId);
  if (!user) {
    return { ok: false, error: "Account not found." };
  }
  await updateUser(user.id, { passwordHash: hashPassword(newPassword) });
  await markResetUsed(token);
  return { ok: true, data: null };
}
