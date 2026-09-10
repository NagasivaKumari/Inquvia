"use client";

import { useEffect, useState } from "react";
import { ALGORAND_CONFIG, ORCHESTRATOR_CONFIG } from "@/lib/config";
import styles from "./page.module.css";

interface LeaderboardItem {
  rank: number;
  id: string;
  label?: string | null;
  sub?: string | null;
  address: string;
  bazaar: boolean;
  challenge: boolean;
  volume: number;
  settles: number;
}

interface LeaderboardResponse {
  cat: string;
  items: LeaderboardItem[];
  total: number;
}

interface SourceRow {
  key: string;
  label: string;
  description: string;
  item?: LeaderboardItem;
  total: number;
}

const SOURCES: { key: string; label: string; description: string }[] = [
  { key: "x402-global-challenge", label: "Global Challenge", description: "x402-global-challenge tag attribution" },
  { key: "bazaar", label: "Bazaar", description: "Visible in the Bazaar catalog" },
  { key: "direct", label: "Direct", description: "Settlements not via Bazaar/discovery" },
  { key: "dev", label: "Developer", description: "Localhost / bot traffic — not challenge volume" },
];

const CONFIGURED_SOURCES = SOURCES.map((source) =>
  source.key === "x402-global-challenge"
    ? { ...source, key: ALGORAND_CONFIG.challengeTag }
    : source
);

export default function FacilitatorPage() {
  const [rows, setRows] = useState<SourceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const payTo = ORCHESTRATOR_CONFIG.payTo;
  const network = ALGORAND_CONFIG.network;

  useEffect(() => {
    if (!payTo) {
      setRows([]);
      return;
    }
    Promise.all(
      CONFIGURED_SOURCES.map(async (s) => {
        try {
          const res = await fetch(
            `${ALGORAND_CONFIG.facilitatorUrl}/data/leaderboards?cat=merchants&limit=2000&range=all&env=${network}&src=${s.key}`
          );
          if (!res.ok) throw new Error(`${res.status}`);
          const data: LeaderboardResponse = await res.json();
          const item = data.items.find((i) => i.address === payTo);
          return { ...s, item: item ?? undefined, total: data.total };
        } catch {
          return { ...s, item: undefined, total: 0 };
        }
      })
    )
      .then(setRows)
      .catch(() => setError("Failed to load facilitator data."));
  }, [payTo, network]);

  const challenge = rows?.find((r) => r.key === ALGORAND_CONFIG.challengeTag);
  const found = rows
    ?.filter((row) => row.item)
    .sort((a, b) => (b.item?.settles ?? 0) - (a.item?.settles ?? 0))[0]?.item;

  const boardUrl = (src: string) =>
    `${ALGORAND_CONFIG.facilitatorUrl}/dashboard/leaderboards?cat=merchants&env=${network}&src=${src}&range=all`;

  const explorerUrl = `https://${network === "testnet" ? "testnet." : ""}algoexplorer.io/address/${payTo}`;

  if (!payTo) {
    return (
      <div className="empty-state">
        <h2 className="heading-md">Facilitator dashboard</h2>
        <p>Set INQUVIA_PAYTO_ADDRESS in your environment to track this merchant on the GoPlausible leaderboards.</p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className="heading-lg">Facilitator</h1>
        <p className="text-muted">
          GoPlausible x402 settlement view for {payTo.slice(0, 8)}…{payTo.slice(-6)} · {network}
        </p>
      </header>

      {error && <p className="text-muted">{error}</p>}

      {!rows && !error && <p className="text-muted animate-pulse">Loading facilitator data…</p>}

      {rows && (
        <>
          <div className={styles.summary}>
            <div className={`card ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Challenge rank</span>
              <span className={challenge?.item ? styles.summaryValue : styles.rankNone}>
                {challenge?.item ? `#${challenge.item.rank}` : "Not ranked"}
                {challenge?.total ? <span className={styles.summarySuffix}>of {challenge.total}</span> : null}
              </span>
            </div>
            <div className={`card ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Volume</span>
              <span className={styles.summaryValue}>
                ${(found?.volume ?? 0).toFixed(2)}
                <span className={styles.summarySuffix}>USDC</span>
              </span>
            </div>
            <div className={`card ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Settlements</span>
              <span className={styles.summaryValue}>{found?.settles ?? 0}</span>
            </div>
            <div className={`card ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Merchant</span>
              <span className={styles.summaryValue} style={{ fontSize: 14 }}>
                {found?.label ?? "—"}
              </span>
              {found?.sub && <span className={styles.summaryLabel}>{found.sub}</span>}
            </div>
          </div>

          <div className={styles.grid}>
            <section className={`card ${styles.section}`}>
              <div className={styles.sectionTitle}>
                <span>Attribution</span>
                <a className={styles.sectionLink} href={boardUrl("x402-global-challenge")} target="_blank" rel="noreferrer">
                  Open leaderboard ↗
                </a>
              </div>
              <p className={`text-muted ${styles.muted}`} style={{ fontSize: 13 }}>
                Volume is separated by attribution source. Local development payments appear under Developer; production payments should appear under the configured challenge tag or Bazaar.
              </p>
              <div className={styles.attribution}>
                {rows.map((r) => (
                  <div key={r.key} className={styles.attributionRow}>
                    <div>
                      <div className={styles.attributionName}>
                        {r.label}
                        {r.item && (
                            <span className={`badge ${r.key === ALGORAND_CONFIG.challengeTag ? "badge-success" : r.key === "dev" ? "badge-warning" : "badge-info"}`} style={{ marginLeft: 8 }}>
                            {r.item.volume > 0 ? "active" : "0 vol"}
                          </span>
                        )}
                      </div>
                      <div className={styles.attributionMeta}>{r.description}</div>
                    </div>
                    <div className={styles.attributionValue}>
                      {r.item ? (
                        <>
                          ${r.item.volume.toFixed(2)} · {r.item.settles} settles
                        </>
                      ) : (
                        <span className={styles.attributionEmpty}>none</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className={`card ${styles.section}`}>
              <div className={styles.sectionTitle}>
                <span>Receiving address</span>
                <a className={styles.sectionLink} href={explorerUrl} target="_blank" rel="noreferrer">
                  Open explorer ↗
                </a>
              </div>
              <p className={styles.explorer}>{payTo}</p>
              <ul className={styles.list}>
                <li className={styles.listItem}>
                  <span>Network</span>
                  <code>{network} · USDC ASA {ALGORAND_CONFIG.network === "testnet" ? 10458941 : 31566704}</code>
                </li>
                <li className={styles.listItem}>
                  <span>Challenge tag</span>
                  <code>{ALGORAND_CONFIG.challengeTag}</code>
                </li>
                <li className={styles.listItem}>
                  <span>Facilitator</span>
                  <code>{ALGORAND_CONFIG.facilitatorUrl}</code>
                </li>
                <li className={styles.listItem}>
                  <span>Bazaar listing</span>
                  <code>{found?.bazaar ? "visible" : "not detected"}</code>
                </li>
              </ul>
            </section>
          </div>
        </>
      )}
    </div>
  );
}