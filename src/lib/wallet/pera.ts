"use client";

import { PeraWalletConnect } from "@perawallet/connect";
import algosdk from "algosdk";
import { ALGORAND_CONFIG } from "@/lib/config";

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
    await getPera().disconnect();
  } catch {
    // already disconnected
  }
}

/** Sign an arbitrary message with the user's wallet (proves ownership). */
export async function signChallenge(
  address: string,
  message: string
): Promise<{ signature: Uint8Array }> {
  const data = new TextEncoder().encode(message);
  const signed = await getPera().signData(
    [{ data, message }],
    address,
    true // verify the signature after signing
  );
  return { signature: signed[0] };
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
