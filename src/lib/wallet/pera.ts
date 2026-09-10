"use client";

import { PeraWalletConnect } from "@perawallet/connect";
import algosdk from "algosdk";
import { ALGORAND_CONFIG } from "@/lib/config";

function canonicalJson(value: Record<string, unknown>): string {
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${JSON.stringify(value[key])}`)
    .join(",")}}`;
}

let peraWallet: PeraWalletConnect | null = null;

export function getPera(): PeraWalletConnect {
  if (!peraWallet) {
    peraWallet = new PeraWalletConnect({
      // 416001 = Algorand MainNet, 416002 = TestNet
      chainId: ALGORAND_CONFIG.network === "testnet" ? 416002 : 416001,
    });
  }
  return peraWallet;
}

/** Ensure the Pera WalletConnect session is initialized and connected before signing. */
export async function ensurePeraSession(): Promise<PeraWalletConnect> {
  const pera = getPera();
  if (pera.isConnected) {
    return pera;
  }
  try {
    const accounts = await pera.reconnectSession();
    if (accounts && accounts.length > 0) {
      return pera;
    }
  } catch {
    // Reconnect failed or no active session
  }
  const accounts = await pera.connect();
  if (accounts && accounts.length > 0) {
    return pera;
  }
  throw new Error(
    "Pera connection was not completed. Approve the connect request shown in the Pera app " +
      "(or the QR on screen) before sending the payment."
  );
}

function getAlgod(): algosdk.Algodv2 {
  return new algosdk.Algodv2(
    ALGORAND_CONFIG.algodToken,
    ALGORAND_CONFIG.algodServer,
    ALGORAND_CONFIG.algodPort
  );
}

/** Real Pera connect — returns the user-approved Algorand address(es). */
export async function connectPera(): Promise<{ address: string; providerId: string }> {
  const accounts = await getPera().connect();
  const address = accounts[0];
  return { address, providerId: "pera" };
}

export async function disconnectPera(): Promise<void> {
  try {
    if (peraWallet) {
      await peraWallet.disconnect();
    }
  } catch {
    // already disconnected
  } finally {
    peraWallet = null;
    if (typeof window !== "undefined") {
      try {
        localStorage.removeItem("PeraWallet.Wallet");
        localStorage.removeItem("walletconnect");
      } catch {
        // ignore
      }
    }
  }
}

/**
 * Sign an ARC-60 (Sign-In With Algorand) auth challenge with the user's wallet.
 * Pera's `signData` throws EXTENSION_UNSUPPORTED_OPERATION; only
 * `signArc60Data` works on current Pera, and it returns an ARC-60 framed
 * signature: EdDSA(SHA256(data) || SHA256(authenticatorData)) where
 * authenticatorData[0:32] must equal SHA256(domain).
 */
export async function signChallenge(
  address: string,
  statement: string,
  domain: string
): Promise<{ signature: Uint8Array; authenticatorData: Uint8Array; dataB64: string; message: string }> {
  const encoder = new TextEncoder();
  const authenticatorData = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(domain)));
  const message = canonicalJson({
    account_address: address,
    chain_id: ALGORAND_CONFIG.network === "mainnet" ? "416001" : "416002",
    domain,
    "issued-at": new Date().toISOString(),
    statement,
    type: "ed25519",
    uri: domain,
    version: "1",
  });
  let dataBin = "";
  const messageBytes = encoder.encode(message);
  messageBytes.forEach((b) => (dataBin += String.fromCharCode(b)));
  const dataB64 = btoa(dataBin);

  const payload = {
    data: dataB64,
    signer: algosdk.decodeAddress(address).publicKey,
    domain,
    authenticatorData,
  };
  const signed = await getPera().signArc60Data(
    payload,
    { scope: 1, encoding: "base64" }, // 1 = AUTH
    true // verify the signature after signing
  );
  return {
    signature: signed.signature,
    authenticatorData: signed.authenticatorData ?? authenticatorData,
    dataB64,
    message,
  };
}

/** Sign a USDC asset transfer from the user's wallet to a recipient. */
export async function signAndSendUsdc(opts: {
  from: string;
  to: string;
  amountMicroUsdc: number;
}): Promise<{ txid: string; assetId: number }> {
  const algod = getAlgod();
  const suggestedParams = await algod.getTransactionParams().do();
  const txn = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: opts.from,
    receiver: opts.to,
    amount: opts.amountMicroUsdc,
    assetIndex: Number(ALGORAND_CONFIG.usdcAsa),
    suggestedParams,
  });

  const signed = await getPera().signTransaction([[{ txn, signers: [opts.from] }]]);
  const { txid } = await algod.sendRawTransaction(signed).do();
  const assetId = Number(ALGORAND_CONFIG.usdcAsa);
  return { txid, assetId };
}

/** Check whether an account has opted in to the USDC asset. */
export async function checkAssetOptIn(address: string): Promise<boolean> {
  const algod = getAlgod();
  const assetId = BigInt(ALGORAND_CONFIG.usdcAsa);
  const account = await algod.accountInformation(address).do();
  const assets = account.assets ?? [];
  return assets.some((a) => a.assetId === assetId);
}

/** Build + sign USDC opt-in transaction for the given account. */
export async function signAndSendUsdcOptIn(address: string): Promise<{ txid: string }> {
  const algod = getAlgod();
  const suggestedParams = await algod.getTransactionParams().do();
  const assetId = Number(ALGORAND_CONFIG.usdcAsa);
  const txn = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
    sender: address,
    receiver: address,
    amount: 0,
    assetIndex: assetId,
    suggestedParams,
  });
  const signed = await getPera().signTransaction([[{ txn, signers: [address] }]]);
  const { txid } = await algod.sendRawTransaction(signed).do();
  return { txid };
}
