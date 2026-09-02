import type { Investigation } from "@/lib/types";
import { ASSESSMENT_LABELS, RISK_LABELS } from "@/lib/types";
import { EvidenceBoard } from "@/components/evidence/EvidenceBoard";
import styles from "./ResultPanel.module.css";

interface Props {
  investigation: Investigation;
}

export function ResultPanel({ investigation }: Props) {
  const supporting = investigation.evidence.filter((e) =>
    investigation.supportingEvidenceIds.includes(e.id)
  );
  const contradictory = investigation.evidence.filter((e) =>
    investigation.contradictoryEvidenceIds.includes(e.id)
  );

  const assessmentClass = {
    likely_genuine: styles.genuine,
    likely_misleading: styles.misleading,
    suspicious: styles.suspicious,
    insufficient_evidence: styles.insufficient,
    inconclusive: styles.inconclusive,
  }[investigation.conclusion];

  return (
    <section className={styles.section} aria-labelledby="result-heading">
      <div className={`card ${styles.assessment} ${assessmentClass}`}>
        <h2 id="result-heading" className="sr-only">
          Investigation result
        </h2>
        <p className={styles.assessmentLabel}>Assessment</p>
        <p className={styles.assessmentValue}>
          {ASSESSMENT_LABELS[investigation.conclusion]}
        </p>

        <div className={styles.metrics}>
          <div>
            <span className={styles.metricLabel}>Confidence</span>
            <span className={styles.metricValue}>
              {investigation.confidence}%
            </span>
          </div>
          <div>
            <span className={styles.metricLabel}>Risk</span>
            <span className={styles.metricValue}>
              {RISK_LABELS[investigation.risk]}
            </span>
          </div>
        </div>

        <p className={styles.conclusionText}>
          {investigation.conclusionText}
        </p>
      </div>

      {investigation.findings.length > 0 && (
        <div className={styles.findings}>
          <h3 className="heading-sm">What we found</h3>
          <ul>
            {investigation.findings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {supporting.length > 0 && (
        <EvidenceBoard items={supporting} title="Supporting evidence" />
      )}

      {contradictory.length > 0 && (
        <EvidenceBoard items={contradictory} title="Contradictory evidence" />
      )}

      {investigation.limitations.length > 0 && (
        <div className={`card ${styles.limitations}`}>
          <h3 className="heading-sm">What we could not verify</h3>
          <ul>
            {investigation.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
