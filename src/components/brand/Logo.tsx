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
        <img src="/logo.png" alt={`${APP_NAME} logo`} width={140} height={32} />
      </span>
      {!compact && <span className={styles.name}>{APP_NAME}</span>}
    </Link>
  );
}
