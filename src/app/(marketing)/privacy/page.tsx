import Link from "next/link";
import { APP_NAME } from "@/lib/config";

export const metadata = { title: "Privacy Policy" };

export default function PrivacyPage() {
  return (
    <div className="container mkt-legal">
      <h1 className="heading-lg">Privacy Policy</h1>
      <p className="text-muted" style={{ marginBottom: "var(--space-6)" }}>
        Last updated: {new Date().toISOString().slice(0, 10)}
      </p>
      <div className="card" style={{ lineHeight: 1.7 }}>
        <p style={{ color: "var(--color-text-muted)" }}>
          {APP_NAME} stores your account details and investigations in a local
          database. Seed phrases, private keys, and mnemonic phrases are never
          requested, stored, or exposed. Only public wallet addresses are stored
          when you connect a wallet. Your investigations are private to your
          account, and your password is stored only as a secure hash.
        </p>
      </div>
      <Link href="/signup" className="btn btn-secondary" style={{ marginTop: "var(--space-6)" }}>Back to signup</Link>
    </div>
  );
}
