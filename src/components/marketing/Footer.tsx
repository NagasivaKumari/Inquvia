import Link from "next/link";
import { APP_NAME } from "@/lib/config";
import styles from "./Footer.module.css";

const PRODUCT_LINKS = [
  { label: "How It Works", href: "/how-it-works" },
  { label: "Investigate", href: "/investigate" },
  { label: "What You Can Check", href: "/#capabilities" },
  { label: "Evidence", href: "/#evidence" },
  { label: "Pricing", href: "/#capabilities" },
];

const COMPANY_LINKS = [
  { label: "About", href: "/how-it-works" },
  { label: "Dashboard", href: "/dashboard" },
  { label: "Sign In", href: "/login" },
  { label: "Register", href: "/signup" },
];

const RESOURCE_LINKS = [
  { label: "Documentation", href: "/how-it-works" },
  { label: "Algorand", href: "https://algorand.com", external: true },
  { label: "x402 Protocol", href: "https://x402.org", external: true },
  { label: "Terms of Use", href: "/terms" },
  { label: "Privacy Policy", href: "/privacy" },
];

export function Footer() {
  return (
    <footer className={styles.footerWrap} aria-label="Site Footer">
      <div className={`container ${styles.footerInner}`}>
        <div className={styles.mainGrid}>
          {/* BRAND COLUMN */}
          <div className={styles.brandCol}>
            <Link href="/" className={styles.brandLogo}>
              <img
                src="/logo.png"
                alt={`${APP_NAME} logo`}
                className={styles.logoMark}
                width={34}
                height={34}
              />
              <span className={styles.logoText}>{APP_NAME}</span>
            </Link>
            <h3 className={styles.brandHeading}>
              Investigate before you decide.
            </h3>
            <p className={styles.brandSub}>
              Real evidence. Real analysis. Real trust.
            </p>
          </div>

          {/* PRODUCT COLUMN */}
          <div className={styles.navCol}>
            <span className={styles.colTitle}>Product</span>
            <ul className={styles.linkList}>
              {PRODUCT_LINKS.map((link) => (
                <li key={link.label}>
                  <Link href={link.href} className={styles.navLink}>
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* COMPANY COLUMN */}
          <div className={styles.navCol}>
            <span className={styles.colTitle}>Company</span>
            <ul className={styles.linkList}>
              {COMPANY_LINKS.map((link) => (
                <li key={link.label}>
                  <Link href={link.href} className={styles.navLink}>
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* RESOURCES COLUMN */}
          <div className={styles.navCol}>
            <span className={styles.colTitle}>Resources</span>
            <ul className={styles.linkList}>
              {RESOURCE_LINKS.map((link) => (
                <li key={link.label}>
                  {link.external ? (
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noreferrer"
                      className={styles.navLink}
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link href={link.href} className={styles.navLink}>
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* ALGORAND & x402 TRUST PANEL */}
          <div className={styles.trustCol}>
            <a
              href="https://algorand.com"
              target="_blank"
              rel="noreferrer"
              className={styles.trustCard}
              title="Built on Algorand"
            >
              <div className={styles.trustCardHeader}>
                <div className={styles.trustHeaderLeft}>
                  <div className={styles.trustLogoWrap}>
                    <svg
                      width="24"
                      height="24"
                      viewBox="0 0 100 100"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      aria-label="Algorand Logo"
                    >
                      <path
                        d="M57.6 15L74.8 62.9H60.2L49.1 31.9L37.1 62.9H22.5L50.7 15H57.6ZM43.4 51.5L47.7 40.4L52.1 51.5H43.4Z"
                        fill="#38BDF8"
                      />
                    </svg>
                  </div>
                  <div className={styles.trustCardTitleWrap}>
                    <h4 className={styles.trustTitle}>Built on Algorand</h4>
                    <span className={styles.trustProtocol}>x402 Protocol</span>
                  </div>
                </div>
                <span className={styles.trustExternalLink} aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 17l9.2-9.2M17 17V8H8" />
                  </svg>
                </span>
              </div>
              <p className={styles.trustDesc}>
                Secure micropayments. Transparent and verifiable. Open for a more informed world.
              </p>
            </a>

            <div className={styles.trustPillars}>
              <div className={styles.trustPillarItem}>
                <div className={styles.trustPillarIcon} aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <path d="M9 12l2 2 4-4" />
                  </svg>
                </div>
                <span className={styles.trustPillarLabel}>
                  On-chain<br />payments
                </span>
              </div>

              <div className={styles.trustPillarItem}>
                <div className={styles.trustPillarIcon} aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <span className={styles.trustPillarLabel}>
                  Independent<br />evidence sources
                </span>
              </div>

              <div className={styles.trustPillarItem}>
                <div className={styles.trustPillarIcon} aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                </div>
                <span className={styles.trustPillarLabel}>
                  Verifiable<br />assessments
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* BOTTOM COPYRIGHT ROW */}
        <div className={styles.bottomBar}>
          <span className={styles.copyright}>
            &copy; {new Date().getFullYear()} {APP_NAME}. All rights reserved.
          </span>
          <span className={styles.motto}>
            Evidence for a more informed world.
          </span>
        </div>
      </div>
    </footer>
  );
}
