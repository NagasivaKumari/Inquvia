import type { Investigation } from "@/lib/types";
import {
  ASSESSMENT_LABELS,
  CONTEXTUAL_ACCURACY_LABELS,
  MEDIA_AUTHENTICITY_LABELS,
  RISK_LABELS,
} from "@/lib/types";
import { EvidenceBoard } from "@/components/evidence/EvidenceBoard";
import styles from "./ResultPanel.module.css";

interface Props {
  investigation: Investigation;
  hideEvidence?: boolean;
}

export function ResultPanel({ investigation, hideEvidence = false }: Props) {
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
    answered: styles.answered,
  }[investigation.conclusion];

  // Layered image investigations carry a second-level distinction: whether
  // the FILE is genuine vs whether the CONTENT is accurate in its context.
  // These are independent — an authentic file can still be misleading in
  // context, and a manipulated file can still be an accurate reproduction.
  const hasVerdicts = Boolean(
    investigation.mediaAuthenticity || investigation.contextualAccuracy
  );
  const authenticity = investigation.mediaAuthenticity;
  const accuracyCtx = investigation.contextualAccuracy;
  const provenance = investigation.provenance;
  const trace = investigation.investigationTrace ?? [];
  const externalEvidence = investigation.externalEvidence ?? [];
  const evidenceAssessment = investigation.evidenceAssessment;
  const batchAnalysis = investigation.batchAnalysis;
  const toneClass = {
    authentic: styles.toneAuthentic,
    accurate: styles.toneAccurate,
    manipulated: styles.toneManipulated,
    misleading: styles.toneMisleading,
    false: styles.toneFalse,
    ai_generated: styles.toneAiGenerated,
    unknown: styles.toneUnknown,
  } as Record<string, string>;

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

      {hasVerdicts && (
        <div className={styles.verdicts}>
          {authenticity && (
            <div className={`card ${styles.verdict}`}>
              <p className={styles.verdictLabel}>Media authenticity</p>
              <p className={`${styles.verdictValue} ${toneClass[authenticity.verdict]}`}>
                {MEDIA_AUTHENTICITY_LABELS[authenticity.verdict]}
              </p>
              {typeof authenticity.confidence === "number" && (
                <p className={styles.verdictConfidence}>
                  {authenticity.confidence}% confidence
                </p>
              )}
              <p className={styles.verdictReasoning}>{authenticity.reasoning}</p>
            </div>
          )}
          {accuracyCtx && (
            <div className={`card ${styles.verdict}`}>
              <p className={styles.verdictLabel}>Contextual accuracy</p>
              <p className={`${styles.verdictValue} ${toneClass[accuracyCtx.verdict]}`}>
                {CONTEXTUAL_ACCURACY_LABELS[accuracyCtx.verdict]}
              </p>
              {typeof accuracyCtx.confidence === "number" && (
                <p className={styles.verdictConfidence}>
                  {accuracyCtx.confidence}% confidence
                </p>
              )}
              <p className={styles.verdictReasoning}>{accuracyCtx.reasoning}</p>
            </div>
          )}
        </div>
      )}

      {investigation.medicalInvestigation && (
        <div className={`card ${styles.limitations}`}>
          <h3 className="heading-sm">Medical image notice</h3>
          <p className={styles.conclusionText}>
            This investigation involves medical imaging. Results are not a medical
            diagnosis or clinical assessment. Consult qualified healthcare professionals
            and specialized medical imaging systems for clinical use.
          </p>
        </div>
      )}

      {batchAnalysis && batchAnalysis.clusterCount > 0 && (
        <div className={`card ${styles.batch}`}>
          <h3 className="heading-sm">Batch analysis</h3>
          <p className={styles.conclusionText}>
            {batchAnalysis.imageCount} images → {batchAnalysis.clusterCount} cluster(s),{" "}
            {batchAnalysis.duplicateClusterCount} duplicate cluster(s).
          </p>
          <ul>
            {(batchAnalysis.clusters ?? [])
              .filter((c) => (c.memberCount ?? 0) > 1)
              .map((c) => (
                <li key={c.clusterId}>
                  Cluster {c.clusterId}: {c.memberCount} near-duplicate(s) —{" "}
                  {(c.members ?? []).map((m) => m.label || m.fileName).join(", ")}
                </li>
              ))}
          </ul>
        </div>
      )}

      {trace.length > 0 && (
        <div className={`card ${styles.trace}`}>
          <h3 className="heading-sm">Investigation trace</h3>
          <ul className={styles.traceList}>
            {trace.map((entry, i) => (
              <li key={i}>
                <span className={styles.traceStatus}>
                  {entry.status === "completed" ? "✓" : entry.status === "unavailable" ? "○" : "—"}
                </span>{" "}
                {entry.check}
                {entry.detail ? ` — ${entry.detail}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {evidenceAssessment && (
        <div className={styles.evidenceSections}>
          {evidenceAssessment.observed && evidenceAssessment.observed.length > 0 && (
            <div className={`card ${styles.evidenceSection}`}>
              <h3 className="heading-sm">What the image directly shows</h3>
              <ul>
                {evidenceAssessment.observed.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {evidenceAssessment.externallyVerified &&
            evidenceAssessment.externallyVerified.length > 0 && (
              <div className={`card ${styles.evidenceSection}`}>
                <h3 className="heading-sm">Externally verified</h3>
                <ul>
                  {evidenceAssessment.externallyVerified.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
          {evidenceAssessment.inferred && evidenceAssessment.inferred.length > 0 && (
            <div className={`card ${styles.evidenceSection}`}>
              <h3 className="heading-sm">Inferred (not independently verified)</h3>
              <ul>
                {evidenceAssessment.inferred.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {evidenceAssessment.unknown && evidenceAssessment.unknown.length > 0 && (
            <div className={`card ${styles.evidenceSection}`}>
              <h3 className="heading-sm">Could not verify</h3>
              <ul>
                {evidenceAssessment.unknown.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {externalEvidence.length > 0 && (
        <div className={`card ${styles.externalEvidence}`}>
          <h3 className="heading-sm">External evidence</h3>
          <ul>
            {externalEvidence.map((src, i) => (
              <li key={i}>
                <strong>{src.sourceName}</strong>
                {src.url ? (
                  <>
                    {" "}
                    —{" "}
                    <a href={src.url} target="_blank" rel="noreferrer noopener">
                      {src.url}
                    </a>
                  </>
                ) : null}
                <br />
                <span className={styles.evidenceMeta}>
                  {src.sourceType}
                  {src.confidence ? ` · ${src.confidence} confidence` : ""}
                </span>
                <br />
                {src.finding}
              </li>
            ))}
          </ul>
        </div>
      )}

      {investigation.forensicFindings && investigation.forensicFindings.length > 0 && (
        <div className={`card ${styles.forensics}`}>
          <h3 className="heading-sm">Forensic findings</h3>
          <ul>
            {investigation.forensicFindings.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {provenance && provenance.note && (
        <div className={`card ${styles.provenance}`}>
          <h3 className="heading-sm">Provenance</h3>
          <p className={styles.conclusionText}>
            {provenance.provenanceEstablished
              ? `Near-duplicates found: ${provenance.nearDuplicatesFound}.`
              : "No web provenance was established."}{" "}
            {provenance.note}
          </p>
          {provenance.earliestSource?.link && (
            <p className={styles.conclusionText}>
              Earliest known copy:{" "}
              <a
                href={provenance.earliestSource.link}
                target="_blank"
                rel="noreferrer noopener"
              >
                {provenance.earliestSource.link}
              </a>
              {provenance.earliestSource.date
                ? ` (dated ${provenance.earliestSource.date})`
                : ""}
            </p>
          )}
        </div>
      )}

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

      {!hideEvidence && supporting.length > 0 && (
        <EvidenceBoard items={supporting} title="Supporting evidence" />
      )}

      {!hideEvidence && contradictory.length > 0 && (
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
