"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE, PUBLIC_NAV } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { Logo } from "@/components/brand/Logo";
import styles from "./PublicNav.module.css";

export function PublicNav() {
  const [user, setUser] = useState<{ name: string } | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => setUser(d.user ?? null))
      .catch(() => {});
  }, []);

  const close = () => setOpen(false);

  return (
    <div className={styles.wrap}>
      <header className={styles.header}>
        <div className={`container ${styles.inner}`}>
          <span className={styles.logoPill}>
            <Logo href="/" />
          </span>

          <nav className={styles.nav} aria-label="Primary">
            {PUBLIC_NAV.map((l) => (
              <a key={l.href} href={l.href} className={styles.navLink} onClick={close}>
                {l.label}
              </a>
            ))}
          </nav>

          <div className={styles.cta}>
            {user ? (
              <Link href="/dashboard" className="btn btn-primary btn-sm">
                Open workspace
              </Link>
            ) : (
              <Link href="/login" className={`btn btn-primary btn-sm ${styles.primaryBtn}`}>
                Sign in to Inquvia
              </Link>
            )}
          </div>

          <button
            className={styles.burger}
            onClick={() => setOpen((o) => !o)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            type="button"
          >
            <span className={styles.burgerIcon} aria-hidden="true">
              {open ? (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              ) : (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M3 12h18M3 18h18" />
                </svg>
              )}
            </span>
          </button>
        </div>

        {open && (
          <div className={styles.mobileDrawer}>
            {PUBLIC_NAV.map((l) => (
              <a key={l.href} href={l.href} className={styles.mobileLink} onClick={close}>
                {l.label}
              </a>
            ))}
            <div className={styles.mobileCta}>
              {user ? (
                <Link href="/dashboard" className="btn btn-primary" onClick={close}>
                  Workspace
                </Link>
              ) : (
                <Link href="/login" className="btn btn-primary" onClick={close}>
                  Sign in to Inquvia
                </Link>
              )}
            </div>
          </div>
        )}
      </header>
    </div>
  );
}
