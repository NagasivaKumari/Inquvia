import type { CapabilityNeed } from "@/lib/types";
import styles from "./PlanCard.module.css";

interface Props {
  items: CapabilityNeed[];
}

export function InvestigationPlan({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <section className={styles.section} aria-labelledby="plan-heading">
      <h2 id="plan-heading" className="heading-md">
        Investigation plan
      </h2>
      <p className="text-sm text-muted">
        The agent determined that it needs the following evidence checks:
      </p>
      <div className={styles.grid}>
        {items.map((item) => (
          <div key={item.id} className={`card ${styles.card}`}>
            <div className={styles.header}>
              <h3 className="heading-sm">{formatCapability(item.capability)}</h3>
              <StatusBadge status={item.status} />
            </div>
            <div className={styles.detail}>
              <span className={styles.detailLabel}>Why</span>
              <p>{item.reason}</p>
            </div>
            <div className={styles.meta}>
              <div>
                <span className={styles.detailLabel}>Cost</span>
                <span>${(item.estimatedCost ?? 0).toFixed(3)}</span>
              </div>
              <div>
                <span className={styles.detailLabel}>Expected value</span>
                <span>{Math.round((item.expectedValue ?? 0) * 100)}%</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: CapabilityNeed["status"] }) {
  const map: Record<string, { label: string; className: string }> = {
    pending: { label: "Pending", className: "badge-neutral" },
    selected: { label: "Selected", className: "badge-info" },
    purchased: { label: "Purchased", className: "badge-success" },
    failed: { label: "Failed", className: "badge-danger" },
    skipped: { label: "Skipped", className: "badge-neutral" },
  };
  const cfg = map[status] ?? map.pending;
  return <span className={`badge ${cfg.className}`}>{cfg.label}</span>;
}

function formatCapability(cap: string): string {
  return cap
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
