import Link from "next/link";
import { APP_NAME } from "@/lib/config";

export const metadata = { title: "Terms of Service" };

export default function TermsPage() {
  return (
    <div className="container mkt-legal">
      <h1 className="heading-lg">Terms of Service</h1>
      <p className="text-muted" style={{ marginBottom: "var(--space-6)" }}>
        Last updated: {new Date().toISOString().slice(0, 10)}
      </p>
      <div className="card" style={{ lineHeight: 1.7 }}>
        <p style={{ color: "var(--color-text-muted)" }}>
          These are the terms for {APP_NAME}. By using this application you agree
          to use it responsibly and not to misuse investigation tooling. Real USDC
          funds are spent on evidence checks via x402, and every payment is
          authorized by you and fully documented.
        </p>
      </div>
      <Link href="/signup" className="btn btn-secondary" style={{ marginTop: "var(--space-6)" }}>Back to signup</Link>
    </div>
  );
}
