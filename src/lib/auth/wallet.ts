"use client";

import { API_BASE } from "@/lib/config";
import { connectPera, signChallenge } from "@/lib/wallet/pera";

function base64(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary);
}

export async function authenticateWithWallet(remember = true): Promise<{ token: string }> {
  const wallet = await connectPera();
  const { signature, authenticatorData, message } = await signChallenge(
    wallet.address,
    "Sign in to Inquvia with your wallet",
    window.location.origin,
  );
  const response = await fetch(`${API_BASE}/api/auth/wallet`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    cache: "no-store",
    body: JSON.stringify({
      providerId: wallet.providerId,
      address: wallet.address,
      message,
      authenticatorData: base64(authenticatorData),
      signatureB64: base64(signature),
      remember,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? "Wallet authentication failed");
  return data as { token: string };
}