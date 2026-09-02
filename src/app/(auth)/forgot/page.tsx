"use client";

import { useState } from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/config";
import styles from "../auth.module.css";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Request failed");
      setToken(data.token ?? "");
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  if (sent) {
    return (
      <>
        <header className={styles.header}>
          <h1>Check your inbox</h1>
          <p>Reset your password</p>
        </header>

        <div className={styles.formBox}>
          <div className={styles.success}>
            If an account exists with this email, we&apos;ll send a password
            reset link.
          </div>

          {token && (
            <div style={{ marginTop: "var(--space-4)" }}>
              <p className="text-sm text-faint" style={{ marginBottom: 8 }}>
                No email service configured on this prototype — use this reset
                link instead:
              </p>
              <div className={styles.token}>
                {`${typeof window !== "undefined" ? window.location.origin : ""}/reset?token=${token}`}
              </div>
              <Link
                href={`/reset?token=${encodeURIComponent(token)}`}
                className="btn btn-secondary btn-sm"
                style={{ marginTop: "var(--space-3)" }}
              >
                Open reset page
              </Link>
            </div>
          )}
        </div>

        <p className={styles.footer}>
          <Link href="/login">Back to login</Link>
        </p>
      </>
    );
  }

  return (
    <>
      <header className={styles.header}>
        <h1>Reset your password</h1>
        <p>Enter the email associated with your account.</p>
      </header>

      <div className={styles.formBox}>
        <form onSubmit={handleSubmit} className={styles.form}>
          <div className="form-group">
            <label htmlFor="email" className="form-label">Email</label>
            <input
              id="email"
              type="email"
              className="form-input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </div>

          {error && <div className={styles.error} role="alert">{error}</div>}

          <button type="submit" className="btn btn-primary btn-lg" disabled={loading}>
            {loading ? "Sending…" : "Send Reset Link"}
          </button>
        </form>
      </div>

      <p className={styles.footer}>
        <Link href="/login">Back to login</Link>
      </p>
    </>
  );
}
