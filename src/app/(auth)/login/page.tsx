"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { API_BASE } from "@/lib/config";
import { invalidateAuthCache } from "@/lib/api";
import styles from "../auth.module.css";

/** Same-origin path after login. Hard-navigate so the session cookie is sent. */
function postLoginPath(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("://")) {
    return "/dashboard";
  }
  const [path, rest] = raw.split(/([?#].*)/, 2);
  const clean = path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
  if (
    clean === "/login" ||
    clean.startsWith("/login") ||
    clean === "/signup" ||
    clean.startsWith("/signup") ||
    clean === "/reset" ||
    clean === "/forgot"
  ) {
    return "/dashboard";
  }
  return `${clean}${rest ?? ""}`;
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = postLoginPath(searchParams.get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // If the user already has an active session, redirect to the dashboard immediately
  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    if (!token) return;
    fetch(`${API_BASE}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    })
      .then((r) => r.json())
      .then((data) => {
        if (data?.user) {
          router.replace(next);
        }
      })
      .catch(() => {});
  }, [next, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    console.log("handleSubmit: started");
    setError("");
    setLoading(true);
    try {
      console.log("handleSubmit: calling fetch");
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({ email, password, remember }),
      });
      const data = await res.json();
      console.log("handleSubmit: fetch complete", { ok: res.ok, data });
      if (!res.ok) throw new Error(data.error ?? "Login failed");
      
      // Store JWT
      localStorage.setItem("token", data.token);
      invalidateAuthCache();
      
      console.log("handleSubmit: redirecting to", next);
      router.push(next);
      router.refresh();
      window.location.href = next;
    } catch (err) {
      console.error("handleSubmit: error occurred", err);
      setError(err instanceof Error ? err.message : "Something went wrong");
      setLoading(false);
    }
  };

  return (
    <>
      <header className={styles.header}>
        <h1>Login</h1>
        <p>Use your account to continue investigations in the workspace.</p>
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

          <div className="form-group">
            <label htmlFor="password" className="form-label">Password</label>
            <div className="field">
              <input
                id="password"
                type={show ? "text" : "password"}
                className="form-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
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
          </div>

          <div className={styles.rowBetween}>
            <label>
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              />
              <span style={{ marginLeft: 6 }}>Remember session</span>
            </label>
            <Link href="/forgot" className={styles.linkBtn}>
              Forgot password?
            </Link>
          </div>

          {error && <div className={styles.error} role="alert">{error}</div>}

          <button type="submit" className="btn btn-primary btn-lg" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>

      <p className={styles.footer}>
        Don&apos;t have an account? <Link href="/signup">Register</Link>
      </p>
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="text-muted">Loading…</div>}>
      <LoginForm />
    </Suspense>
  );
}
