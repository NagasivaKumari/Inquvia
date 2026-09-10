import type { NextConfig } from "next";

// The backend is configured ONLY through environment variables — nothing is
// hardcoded here.
//
// Vercel production:
//   Set NEXT_PUBLIC_API_URL=https://inquvia.onrender.com in the Vercel project
//   (Settings → Environment Variables → rebuild). The build fails fast without
//   it so a broken blank deployment can never ship.
//
// Render (static export / same-origin): nothing needed — /api calls are
// relative and hit the Render backend directly. VERCEL is unset there.
const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

if (process.env.VERCEL === "1" && !apiUrl) {
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set. Add it to the Vercel environment variables " +
      "(e.g. https://inquvia.onrender.com) and redeploy."
  );
}

const backendUrl = apiUrl || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  images: { unoptimized: true },
  async rewrites() {
    return [
      {
        source: "/.well-known/x402",
        destination: `${backendUrl}/.well-known/x402`,
      },
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;