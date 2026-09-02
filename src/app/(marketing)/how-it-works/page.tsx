import Link from "next/link";
import { APP_NAME, PIPELINE_STEPS, MEDIA } from "@/lib/config";
import styles from "./page.module.css";

export default function HowItWorksPage() {
  return (
    <div className={styles.page}>
      <header className={styles.hero}>
        <div className="container">
          <p className="section-kicker">Technology</p>
          <h1 className={styles.title}>{`How ${APP_NAME} works`}</h1>
          <p className={styles.lede}>
            One paid, evidence-backed investigation across real x402 endpoints.
            You pay {APP_NAME}; it pays evidence services when they exist; you
            receive a verified result.
          </p>
        </div>
      </header>

      <div className="container">
        <figure className={styles.banner}>
          <img src={MEDIA.image} alt={MEDIA.imageAlt} />
        </figure>

        <p className={styles.hint}>
          Every payment in this pipeline is intended to settle on-chain. If a
          downstream service is not discovered, the case reports that gap.
        </p>

        <ol className={styles.flow}>
          {PIPELINE_STEPS.map((step, i) => (
            <li key={step.title} className={styles.step}>
              <div className={styles.node}>
                <span className={styles.num}>{String(i + 1).padStart(2, "0")}</span>
                <div className={styles.body}>
                  <h2 className={styles.stepTitle}>{step.title}</h2>
                  <p className={styles.detail}>{step.detail}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>

        <div className={styles.cta}>
          <Link href="/investigate" className="btn btn-primary btn-lg">
            Start an investigation
          </Link>
          <Link href="/login" className="btn btn-secondary btn-lg">
            Log in to workspace
          </Link>
        </div>
      </div>
    </div>
  );
}
