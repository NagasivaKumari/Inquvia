import { PublicNav } from "@/components/marketing/PublicNav";
import { Logo } from "@/components/brand/Logo";
import { APP_NAME, TAGLINE, FOOTER_COLUMNS } from "@/lib/config";
import "@/styles/marketing.css";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mkt">
      <PublicNav />
      <main>{children}</main>
      <footer className="mkt-footer">
        <div className="container footer-inner">
          <div className="footer-brand">
            <Logo href="/" />
            <p>{TAGLINE}</p>
          </div>
          {FOOTER_COLUMNS.map((col) => (
            <FooterCol key={col.title} title={col.title} links={[...col.links]} />
          ))}
        </div>
        <div className="container footer-bottom">
          <span>
            © {new Date().getFullYear()} {APP_NAME}. All rights reserved.
          </span>
          <div className="footer-links">
            <a href="/terms">Terms of use</a>
            <a href="/privacy">Privacy</a>
            <a href="https://algorand.com" target="_blank" rel="noreferrer">
              Algorand
            </a>
            <a href="https://x402.org" target="_blank" rel="noreferrer">
              x402
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div className="footer-col">
      <span className="footer-col-title">{title}</span>
      <ul>
        {links.map(([label, href]) => (
          <li key={label}>
            <a href={href}>{label}</a>
          </li>
        ))}
      </ul>
    </div>
  );
}
