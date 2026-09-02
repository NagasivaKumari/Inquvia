import type { ProviderScore } from "@/lib/types";
import styles from "./ProviderSelection.module.css";

interface Props {
  scores: ProviderScore[];
}

export function ProviderSelection({ scores }: Props) {
  if (scores.length === 0) return null;

  const selected = scores.find((s) => s.selected);

  return (
    <section className={styles.section} aria-labelledby="provider-heading">
      <h2 id="provider-heading" className="heading-md">
        Economic decision
      </h2>
      <p className="text-sm text-muted">
        Evidence value vs cost — the agent selects the best option.
      </p>

      <div className={styles.table}>
        <div className={styles.tableHeader} role="row">
          <span>Provider</span>
          <span>Cost</span>
          <span>Confidence gain</span>
          <span>Score</span>
          <span>Status</span>
        </div>
        {scores.map((s) => (
          <div
            key={s.providerId}
            className={`${styles.row} ${s.selected ? styles.selected : ""}`}
            role="row"
          >
            <span className={styles.providerId}>{formatId(s.providerId)}</span>
            <span>${s.cost.toFixed(3)}</span>
            <span>{s.expectedConfidenceGain}%</span>
            <span>{s.score}</span>
            <span>
              {s.selected ? (
                <span className="badge badge-success">Selected</span>
              ) : (
                <span className="badge badge-neutral">Not selected</span>
              )}
            </span>
          </div>
        ))}
      </div>

      {selected?.reason && (
        <p className={styles.reason}>
          <strong>Selected because</strong> {selected.reason}
        </p>
      )}
    </section>
  );
}

function formatId(id: string): string {
  const parts = id.replace("prov_", "").split("_");
  return parts
    .slice(0, -1)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
