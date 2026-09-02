import type { StageProgress } from "@/lib/types";
import styles from "./StageProgress.module.css";

interface Props {
  stages: StageProgress[];
  currentStage?: string;
}

export function StageProgressBar({ stages, currentStage }: Props) {
  return (
    <ol className={styles.list} aria-label="Investigation progress">
      {stages.map((stage, index) => {
        const isActive = stage.status === "active";
        const isCompleted = stage.status === "completed";
        const isFailed = stage.status === "failed";

        return (
          <li
            key={stage.id}
            className={`${styles.item} ${styles[stage.status]} ${isActive ? styles.activeItem : ""}`}
            aria-current={isActive ? "step" : undefined}
          >
            <div className={styles.indicator}>
              {isCompleted ? (
                <span className={styles.check} aria-label="Completed">✓</span>
              ) : isFailed ? (
                <span className={styles.fail} aria-label="Failed">✕</span>
              ) : isActive ? (
                <span className={`${styles.dot} animate-pulse`} aria-hidden="true" />
              ) : (
                <span className={styles.dotPending} aria-hidden="true" />
              )}
            </div>
            <div className={styles.content}>
              <span className={styles.label}>{stage.label}</span>
              {isActive && (
                <span className={styles.activeLabel}>In progress</span>
              )}
            </div>
            {index < stages.length - 1 && (
              <div
                className={`${styles.connector} ${isCompleted ? styles.connectorDone : ""}`}
                aria-hidden="true"
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
