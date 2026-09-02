import Link from "next/link";
import { APP_NAME } from "@/lib/config";
import styles from "./Logo.module.css";

export function Logo({
  href = "/",
  inverted = false,
  compact = false,
}: {
  href?: string;
  inverted?: boolean;
  compact?: boolean;
}) {
  return (
    <Link href={href} className={`${styles.logo} ${inverted ? styles.inverted : ""}`}>
      <span className={styles.mark} aria-hidden="true">
        <svg viewBox="0 0 36 36" width="32" height="32" fill="none">
          <rect width="36" height="36" rx="6" fill="currentColor" />
          <path
            d="M10 18.5l5.5 5.5 10.5-12"
            stroke="#fff"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      {!compact && <span className={styles.name}>{APP_NAME}</span>}
    </Link>
  );
}
