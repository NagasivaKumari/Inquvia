import { APP_NAME, MEDIA, PROCESS_STEPS, TAGLINE } from "@/lib/config";
import { Logo } from "@/components/brand/Logo";
import styles from "./auth.module.css";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className={styles.shell}>
      <aside className={styles.panel}>
        <div className={styles.brand}>
          <Logo href="/" inverted />
        </div>
        <figure className={styles.photo}>
          <img src={MEDIA.hero} alt={MEDIA.heroAlt} />
        </figure>
        <div className={styles.panelBody}>
          <p className={styles.kicker}>Access</p>
          <h2 className={styles.quote}>{TAGLINE}</h2>
          <p className={styles.quoteSub}>
            Sign in to run investigations, review reports, and connect a wallet
            when a paid evidence lookup is required.
          </p>
          <ol className={styles.flow}>
            {PROCESS_STEPS.map((s) => (
              <li key={s.n} className={styles.flowItem}>
                <span className={styles.flowNum}>{s.n}</span>
                <span>{s.title}</span>
              </li>
            ))}
          </ol>
        </div>
        <p className={styles.panelFoot}>{APP_NAME} workspace</p>
      </aside>

      <div className={styles.content}>
        <div className={styles.card}>{children}</div>
      </div>
    </div>
  );
}
