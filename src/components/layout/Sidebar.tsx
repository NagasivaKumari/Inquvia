"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE, NAV_ITEMS } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { Logo } from "@/components/brand/Logo";
import { NavIcon } from "@/components/layout/NavIcons";
import styles from "./Sidebar.module.css";

const PRIMARY = [
  { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
  { href: "/investigate", label: "Investigate", icon: "investigate" },
  ...NAV_ITEMS.filter((i) => i.href !== "/investigate" && i.href !== "/settings").map(
    (i) => ({
      ...i,
      icon:
        i.href === "/history"
          ? "history"
          : i.href === "/reports"
            ? "reports"
            : i.href === "/activity"
              ? "activity"
              : "dashboard",
    })
  ),
];

export function Sidebar({
  open = false,
  onNavigate,
}: {
  open?: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{ name: string; email: string } | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((d) => {
        setUser(d.user);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const isActive = (href: string) =>
    pathname === href || (href !== "/dashboard" && pathname.startsWith(href + "/"));

  const handleLogout = async () => {
    localStorage.removeItem("token");
    await apiFetch(`${API_BASE}/api/auth/logout`, { method: "POST" });
    onNavigate?.();
    router.push("/");
    router.refresh();
  };

  return (
    <aside
      className={`${styles.sidebar} ${open ? styles.open : ""}`}
      aria-label="Main navigation"
    >
      <div className={styles.brand}>
        <Logo href="/dashboard" />
      </div>

      <Link href="/investigate" className={styles.newButton} onClick={onNavigate}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New investigation
      </Link>

      <nav className={styles.nav}>
        <p className={styles.navLabel}>Workspace</p>
        {PRIMARY.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`${styles.navLink} ${active ? styles.active : ""}`}
              aria-current={active ? "page" : undefined}
              onClick={onNavigate}
            >
              <span className={styles.navIcon}>
                <NavIcon name={item.icon} />
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className={styles.spacer} />

      <nav className={styles.nav}>
        <p className={styles.navLabel}>Account</p>
        <Link
          href="/settings"
          className={`${styles.navLink} ${isActive("/settings") ? styles.active : ""}`}
          onClick={onNavigate}
        >
          <span className={styles.navIcon}>
            <NavIcon name="settings" />
          </span>
          Settings
        </Link>
      </nav>

      <div className={styles.userBox}>
        {loaded && user ? (
          <>
            <div className={styles.avatar} aria-hidden="true">
              {user.name?.charAt(0)?.toUpperCase() ?? "U"}
            </div>
            <div className={styles.userInfo}>
              <span className={styles.userName}>{user.name}</span>
              <span className={styles.userEmail}>{user.email}</span>
            </div>
            <button onClick={handleLogout} className={styles.logout} aria-label="Log out">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
            </button>
          </>
        ) : loaded && !user ? (
          <Link href="/login" className={styles.loginLink} onClick={onNavigate}>
            Log in
          </Link>
        ) : (
          <div className={`skeleton ${styles.skeletonBox}`} />
        )}
      </div>
    </aside>
  );
}
