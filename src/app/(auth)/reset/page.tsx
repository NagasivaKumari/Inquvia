"use client";

import { useState, Suspense, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE } from "@/lib/config";
import styles from "../auth.module.css";

function ResetForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [state, setState] = useState<"checking" | "valid" | "invalid" | "done">("checking");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/auth/reset?token=${encodeURIComponent(token)}`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setState(d.valid ? "valid" : "invalid"))
      .catch(() => setState("invalid"));
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Reset failed");
      setState("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setState("invalid");
      setLoading(false);
    }
  };

  if (state === "checking") {
    return <div className="animate-pulse text-muted" style={{ textAlign: "center", padding: 40 }}>Checking your reset link…</div>;
  }

  if (state === "invalid") {
    return (
      <>
        <header className={styles.header}>
          <h1>Link unavailable</h1>
        </header>
        <div className={styles.formBox}>
          <p style={{ textAlign: "center", color: "var(--color-text-muted)" }}>
            This password reset link is invalid or has expired.
          </p>
          <div style={{ marginTop: "var(--space-5)", textAlign: "center" }}>
            <Link href="/forgot" className="btn btn-primary btn-lg">
              Request a new reset link
            </Link>
          </div>
        </div>
      </>
    );
  }

  if (state === "done") {
    return (
      <>
        <header className={styles.header}>
          <h1>Password updated successfully</h1>
        </header>
        <div className={styles.formBox}>
          <div className={styles.success}>
            Your password has been reset. You can now log in with your new password.
          </div>
          <div style={{ marginTop: "var(--space-5)", textAlign: "center" }}>
            <Link href="/login" className="btn btn-primary btn-lg">
              Log in
            </Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <header className={styles.header}>
        <h1>Create a new password</h1>
        <p>Choose a strong password to secure your account.</p>
      </header>

      <div className={styles.formBox}>
        <form onSubmit={handleSubmit} className={styles.form}>
          <div className="form-group">
            <label htmlFor="password" className="form-label">New password</label>
            <div className="field">
              <input
                id="password"
                type={show ? "text" : "password"}
                className="form-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
              <button
                type="button"
                className="field-icon"
                onClick={() => setShow((s) => !s)}
                aria-label={show ? "Hide password" : "Show password"}
              >
                {show ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
            <span className="text-xs text-faint">At least 8 characters.</span>
          </div>

          <div className="form-group">
            <label htmlFor="confirm" className="form-label">Confirm new password</label>
            <input
              id="confirm"
              type={show ? "text" : "password"}
              className="form-input"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>

          {error && <div className={styles.error} role="alert">{error}</div>}

          <button type="submit" className="btn btn-primary btn-lg" disabled={loading}>
            {loading ? "Resetting…" : "Reset Password"}
          </button>
        </form>
      </div>
    </>
  );
}

export default function ResetPage() {
  return (
    <Suspense fallback={<div className="animate-pulse">Loading…</div>}>
      <ResetForm />
    </Suspense>
  );
}
