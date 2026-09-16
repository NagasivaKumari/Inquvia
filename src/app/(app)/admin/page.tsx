"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import styles from "./page.module.css";

interface AdminUser {
  id: string;
  name: string;
  email: string;
  walletAddress?: string | null;
  walletNetwork?: string | null;
  createdAt?: string;
  investigationCount?: number;
  lastSeenAt?: string | null;
  totalSpend?: number;
}

export default function AdminPage() {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "active">("all");

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => {
        if (!d.isAdmin) {
          setIsAdmin(false);
          setLoading(false);
          return;
        }
        setIsAdmin(true);
        return apiFetch(`${API_BASE}/api/admin/users`)
          .then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.error ?? "Failed to load users")))))
          .then((d) => {
            setUsers(Array.isArray(d.users) ? d.users : []);
            setLoading(false);
          })
          .catch((err) => {
            setError(err instanceof Error ? err.message : "Something went wrong");
            setLoading(false);
          });
      })
      .catch(() => {
        setError("Not authenticated");
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className={`app-loading ${styles.page}`} />;
  }

  if (!isAdmin) {
    return (
      <div className={styles.page}>
        <h1 className="app-section-title">Admin</h1>
        <p className="text-muted">You don&apos;t have access to this page.</p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin console</p>
        <h1 className="app-section-title">Registered users</h1>
      </div>

      {error && <div className={styles.error} role="alert">{error}</div>}

      <div className={styles.filters}>
        <button
          type="button"
          className={`btn btn-xs ${filter === "all" ? styles.filterActive : "btn-ghost"}`}
          onClick={() => setFilter("all")}
        >
          All ({users.length})
        </button>
        <button
          type="button"
          className={`btn btn-xs ${filter === "active" ? styles.filterActive : "btn-ghost"}`}
          onClick={() => setFilter("active")}
        >
          Used the app ({users.filter((u) => (u.investigationCount ?? 0) > 0).length})
        </button>
      </div>

      <section className={`card ${styles.tableWrap}`}>
        <div className={styles.tableHead}>
          <span>User</span>
          <span>Email</span>
          <span>Wallet</span>
          <span>Investigations</span>
          <span>Last used</span>
        </div>
        {users.length === 0 ? (
          <p className="text-muted" style={{ margin: 0, padding: "var(--space-4)" }}>
            No users yet.
          </p>
        ) : (
          users
            .filter((u) => filter === "all" || (u.investigationCount ?? 0) > 0)
            .map((u) => (
              <div key={u.id} className={styles.row}>
                <span className={styles.name}>{u.name || "—"}</span>
                <span className={styles.email}>{u.email || "—"}</span>
                <span className={u.walletAddress ? "" : "text-faint"}>
                  {u.walletAddress ?? "Not connected"}
                </span>
                <span>{(u.investigationCount ?? 0) > 0 ? (
                  <>
                    {u.investigationCount}
                    {u.totalSpend ? <em className={styles.spend}>${u.totalSpend.toFixed(2)}</em> : null}
                  </>
                ) : (
                  <span className="text-faint">Never used</span>
                )}</span>
                <span className="text-faint">{u.lastSeenAt ? new Date(u.lastSeenAt).toLocaleDateString() : "—"}</span>
              </div>
            ))
        )}
      </section>
    </div>
  );
}