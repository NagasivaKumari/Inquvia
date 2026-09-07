"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE, APP_NAME } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { WalletConnector } from "@/components/wallet/WalletConnector";
import type { PaymentPrefs, User } from "@/lib/types";
import styles from "./page.module.css";

const TABS = [
  { id: "account", label: "Account" },
  { id: "wallet", label: "Wallet" },
  { id: "spending", label: "Spending" },
  { id: "preferences", label: "Preferences" },
  { id: "notifications", label: "Notifications" },
  { id: "security", label: "Security" },
];

export default function SettingsPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("account");
  const [user, setUser] = useState<(Omit<User, "passwordHash"> & { walletAddress?: string; walletNetwork?: string }) | null>(null);
  const [budget, setBudget] = useState<{ spent: number; total: number; remaining: number }>({ spent: 0, total: 0, remaining: 0 });
  const [loaded, setLoaded] = useState(false);
  const [prefs, setPrefs] = useState<PaymentPrefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/user`)
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          setLoaded(true);
          return;
        }
        setUser(d.user);
        setBudget(d.budget);
        setPrefs(d.user.paymentPrefs);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const handleLogout = async () => {
    localStorage.removeItem("token");
    await apiFetch(`${API_BASE}/api/auth/logout`, { method: "POST" });
    router.push("/");
    router.refresh();
  };

  const savePrefs = async () => {
    if (!prefs) return;
    setSaving(true);
    setSaved(false);
    try {
      const res = await apiFetch(`${API_BASE}/api/user`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prefs),
      });
      if (res.ok) {
        setSaved(true);
        const fresh = await apiFetch(`${API_BASE}/api/user`).then((r) => r.json());
        if (!fresh.error) {
          setBudget(fresh.budget);
          setUser(fresh.user);
        }
      }
    } finally {
      setSaving(false);
    }
  };

  const scrollToSection = (tabId: string) => {
    setActiveTab(tabId);
    const element = document.getElementById(tabId);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  if (!loaded) {
    return (
      <div className={styles.settingsContainer}>
        <div className="skeleton" style={{ height: "40px", width: "200px", marginBottom: "20px" }} />
        <div className="skeleton" style={{ height: "400px", width: "100%" }} />
      </div>
    );
  }

  if (!user) {
    return (
      <div className={styles.settingsContainer}>
        <div className={styles.header}>
          <h1 className={styles.headerTitle}>Please Log In</h1>
          <p className={styles.headerSub}>You need to be authenticated to view and edit settings.</p>
          <button
            onClick={() => router.push("/login")}
            className="btn btn-primary"
            style={{ marginTop: "1rem" }}
          >
            Go to Login →
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.settingsContainer}>
      <header className={styles.header}>
        <h1 className={styles.headerTitle}>Settings</h1>
        <p className={styles.headerSub}>Manage your account, wallet and spending controls.</p>
      </header>

      <div className={styles.settingsLayout}>
        {/* Left Sub-Navigation Menu */}
        <aside className={styles.subnav} aria-label="Settings Sub-Navigation">
          <span className={styles.subnavTitle}>Settings</span>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => scrollToSection(tab.id)}
              className={`${styles.subnavItem} ${activeTab === tab.id ? styles.subnavItemActive : ""}`}
            >
              <span>{tab.label}</span>
            </button>
          ))}
        </aside>

        {/* Right Content Panels */}
        <div className={styles.contentArea}>
          {/* 1. Account Section */}
          <section id="account" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Account</h2>
            </div>

            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>Profile Name</span>
              <span className={styles.infoValue}>{user.name}</span>
            </div>

            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>Email</span>
              <span className={styles.infoValue}>{user.email}</span>
            </div>

            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>Password</span>
              <button
                type="button"
                onClick={() => router.push("/forgot")}
                className={styles.resetBtn}
              >
                Reset →
              </button>
            </div>

            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>Account Created</span>
              <span className={styles.infoValue}>
                {new Date(user.createdAt).toLocaleDateString(undefined, {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
              </span>
            </div>
          </section>

          {/* 2. Algorand Wallet Section */}
          <section id="wallet" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Algorand Wallet</h2>
            </div>

            <div
              className={`${styles.walletStatusBox} ${
                user.walletAddress ? styles.statusConnected : styles.statusDisconnected
              }`}
            >
              <span
                className={`${styles.statusDot} ${
                  user.walletAddress ? styles.statusDotConnected : ""
                }`}
              />
              <span>{user.walletAddress ? `Connected: ${user.walletAddress.slice(0, 8)}...` : "○ Not connected"}</span>
            </div>

            <p className={styles.walletNote}>
              Connect your wallet when you need to purchase evidence or enable x402 micropayments on Algorand.
            </p>

            <WalletConnector />
          </section>

          {/* 3. Spending Controls Section */}
          <section id="spending" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Spending Controls</h2>
            </div>

            {prefs && (
              <>
                <div className={styles.spendingInputs}>
                  <div className={styles.spendingRow}>
                    <div className={styles.spendingLabelBox}>
                      <span className={styles.spendingLabel}>Total budget</span>
                      <span className={styles.spendingSub}>Overall cap on what you spend on Inquvia checks</span>
                    </div>
                    <div className={styles.inputPrefixGroup}>
                      <span className={styles.inputPrefix}>$</span>
                      <input
                        type="number"
                        step="0.01"
                        min="0.001"
                        className={`form-input ${styles.spendingInput}`}
                        value={prefs.totalBudget}
                        onChange={(e) =>
                          setPrefs({ ...prefs, totalBudget: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </div>
                  </div>

                  <div className={styles.spendingRow}>
                    <div className={styles.spendingLabelBox}>
                      <span className={styles.spendingLabel}>Per evidence check</span>
                      <span className={styles.spendingSub}>Maximum price per paid external evidence lookup</span>
                    </div>
                    <div className={styles.inputPrefixGroup}>
                      <span className={styles.inputPrefix}>$</span>
                      <input
                        type="number"
                        step="0.001"
                        min="0.001"
                        className={`form-input ${styles.spendingInput}`}
                        value={prefs.maxPerEvidenceCheck}
                        onChange={(e) =>
                          setPrefs({ ...prefs, maxPerEvidenceCheck: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </div>
                  </div>

                  <div className={styles.spendingRow}>
                    <div className={styles.spendingLabelBox}>
                      <span className={styles.spendingLabel}>Per investigation</span>
                      <span className={styles.spendingSub}>Total budget cap for a single multi-step inquiry</span>
                    </div>
                    <div className={styles.inputPrefixGroup}>
                      <span className={styles.inputPrefix}>$</span>
                      <input
                        type="number"
                        step="0.01"
                        min="0.001"
                        className={`form-input ${styles.spendingInput}`}
                        value={prefs.maxPerInvestigation}
                        onChange={(e) =>
                          setPrefs({ ...prefs, maxPerInvestigation: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </div>
                  </div>

                  <div className={styles.spendingRow}>
                    <div className={styles.spendingLabelBox}>
                      <span className={styles.spendingLabel}>Session limit</span>
                      <span className={styles.spendingSub}>Maximum aggregate spend allowed per active session</span>
                    </div>
                    <div className={styles.inputPrefixGroup}>
                      <span className={styles.inputPrefix}>$</span>
                      <input
                        type="number"
                        step="0.01"
                        min="0.001"
                        className={`form-input ${styles.spendingInput}`}
                        value={prefs.sessionBudget}
                        onChange={(e) =>
                          setPrefs({ ...prefs, sessionBudget: parseFloat(e.target.value) || 0 })
                        }
                      />
                    </div>
                  </div>
                </div>

                <div className={styles.saveRow}>
                  <button
                    onClick={savePrefs}
                    className="btn btn-primary"
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save changes"}
                  </button>
                  {saved && (
                    <span className={styles.savedBadge}>
                      ✓ Saved successfully
                    </span>
                  )}
                </div>
              </>
            )}
          </section>

          {/* 4. Investigation Budget Stats */}
          <section className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Investigation Budget</h2>
            </div>

            <div className={styles.budgetGrid}>
              <div className={styles.budgetItem}>
                <span className={styles.budgetLabel}>Total Budget</span>
                <span className={styles.budgetValue}>${budget.total.toFixed(2)}</span>
              </div>
              <div className={styles.budgetItem}>
                <span className={styles.budgetLabel}>Spent</span>
                <span className={styles.budgetValue}>${budget.spent.toFixed(3)}</span>
              </div>
              <div className={styles.budgetItem}>
                <span className={styles.budgetLabel}>Remaining</span>
                <span className={styles.budgetValue} style={{ color: "var(--color-success)" }}>
                  ${budget.remaining.toFixed(3)}
                </span>
              </div>
            </div>
          </section>

          {/* 5. Preferences & Application Section */}
          <section id="preferences" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Preferences</h2>
            </div>

            <div className={styles.infoRow}>
              <span className={styles.infoLabel}>Application Engine</span>
              <span className={styles.infoValue}>{APP_NAME}</span>
            </div>
          </section>

          {/* 6. Notifications Section */}
          <section id="notifications" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Notifications</h2>
            </div>

            <div className={styles.infoRow}>
              <div>
                <div className={styles.infoValue}>Investigation Completed Alerts</div>
                <div className={styles.spendingSub}>Send an email notification when long-running research concludes</div>
              </div>
              <span className="pill pill-success">Enabled</span>
            </div>

            <div className={styles.infoRow}>
              <div>
                <div className={styles.infoValue}>Evidence Purchase Receipts</div>
                <div className={styles.spendingSub}>Receive transaction hash receipts for paid x402 queries</div>
              </div>
              <span className="pill pill-neutral">Digest</span>
            </div>
          </section>

          {/* 7. Security Section */}
          <section id="security" className={styles.cardSection}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Security</h2>
            </div>

            <div className={styles.infoRow}>
              <div>
                <div className={styles.infoValue}>Authentication Password</div>
                <div className={styles.spendingSub}>Last changed during account creation</div>
              </div>
              <button
                type="button"
                onClick={() => router.push("/forgot")}
                className="btn btn-secondary btn-sm"
              >
                Change Password
              </button>
            </div>

            <div className={styles.infoRow} style={{ marginTop: "var(--space-2)" }}>
              <div>
                <div className={styles.infoValue}>Active Session</div>
                <div className={styles.spendingSub}>Log out of this browser session</div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="btn btn-danger btn-sm"
              >
                Log Out
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
