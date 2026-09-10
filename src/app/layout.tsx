import type { Metadata, Viewport } from "next";
import { APP_NAME, TAGLINE } from "@/lib/config";
import "@/styles/globals.css";

const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL ?? process.env.PUBLIC_APP_URL)?.replace(/\/$/, "");
const logoPath = "/logo.png";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export const metadata: Metadata = {
  ...(siteUrl ? { metadataBase: new URL(siteUrl) } : {}),
  title: {
    default: `${APP_NAME} — Autonomous Evidence & AI Fact Investigation`,
    template: `%s | ${APP_NAME}`,
  },
  description: TAGLINE,
  openGraph: {
    type: "website",
    siteName: APP_NAME,
    title: APP_NAME,
    description: TAGLINE,
    ...(siteUrl ? { url: siteUrl } : {}),
    images: [{ url: logoPath, width: 512, height: 512, alt: `${APP_NAME} logo` }],
  },
  twitter: {
    card: "summary",
    title: APP_NAME,
    description: TAGLINE,
    images: [logoPath],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Source+Sans+3:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
