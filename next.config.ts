import type { NextConfig } from "next";

// Production builds (Vercel) default to the Render backend so relative /api/*
// calls work without any env; local dev keeps the local backend.
const defaultBackend =
  process.env.NODE_ENV === "production"
    ? "https://inquvia.onrender.com"
    : "http://127.0.0.1:8000";
const backendUrl = (process.env.NEXT_PUBLIC_API_URL || defaultBackend).replace(/\/$/, "");

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
