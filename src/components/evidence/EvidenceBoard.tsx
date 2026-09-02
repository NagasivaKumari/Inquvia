import type { EvidenceItem } from "@/lib/types";
import { SIGNAL_LABELS } from "@/lib/types";
import styles from "./EvidenceCard.module.css";

interface Props {
  items: EvidenceItem[];
  title?: string;
}

export function EvidenceBoard({ items, title = "Evidence collected" }: Props) {
  if (items.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="evidence-heading">
      <h2 id="evidence-heading" className="heading-md">
        {title}
      </h2>
      <div className={styles.grid}>
        {items.map((item, i) => (
          <div
            key={item.id}
            className={`card ${styles.card} ${styles[item.signal]} animate-in`}
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <div className={styles.header}>
              <span className={styles.type}>{item.type}</span>
              <SignalBadge signal={item.signal} />
            </div>
            <div className={styles.row}>
              <span className={styles.label}>Source</span>
              <span>{item.source}</span>
            </div>
            <div className={styles.finding}>
              <span className={styles.label}>Finding</span>
              <p>{item.finding}</p>
            </div>
            <div className={styles.footer}>
              <span>Confidence: {item.confidence}%</span>
              <span>Cost: ${item.cost.toFixed(3)}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SignalBadge({ signal }: { signal: EvidenceItem["signal"] }) {
  const classMap = {
    supporting: "badge-success",
    contradictory: "badge-warning",
    uncertain: "badge-neutral",
  };
  return (
    <span className={`badge ${classMap[signal]}`}>
      {SIGNAL_LABELS[signal]}
    </span>
  );
}
