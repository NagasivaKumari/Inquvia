"use client";

import styles from "./WalletLogo.module.css";

/**
 * Real wallet logo marks (inline SVG). Pera and Defly only — the two providers
 * Inquvia supports. A little logo the user recognises once their wallet connects.
 */
export function WalletLogo({ id, size = 28 }: { id: string; size?: number }) {
  switch (id) {
    case "defly":
      return (
        <span className={styles.defly} style={{ width: size, height: size }}>
          <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
            <path
              fill="#00B7F1"
              d="M16 2c7.7 0 14 6.3 14 14s-6.3 14-14 14S2 23.7 2 16 8.3 2 16 2Z"
            />
            <path
              fill="#0B0B0E"
              d="M16 5c6.1 0 11 4.9 11 11s-4.9 11-11 11S5 22.1 5 16 9.9 5 16 5Z"
            />
          </svg>
        </span>
      );
    case "pera":
    default:
      return (
        <span className={styles.pera} style={{ width: size, height: size }}>
          <svg viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
            <circle cx="16" cy="16" r="14" fill="#7B3FE4" />
            <path
              fill="#fff"
              d="M11.5 9c.6 0 1 .4 1 1v8.5c0 1.9 1.6 3.5 3.5 3.5s3.5-1.6 3.5-3.5V10c0-.6.4-1 1-1s1 .4 1 1v8.5C21.5 22 19.5 24 16 24s-5.5-2-5.5-4.5V10c0-.6.4-1 1-1Z"
            />
          </svg>
        </span>
      );
  }
}

export const WALLET_BRAND_COLORS: Record<string, string> = {
  pera: "#7B3FE4",
  defly: "#00B7F1",
};