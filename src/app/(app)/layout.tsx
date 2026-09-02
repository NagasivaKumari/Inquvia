"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE } from "@/lib/config";
import { AppShell } from "@/components/layout/AppShell";
import "@/styles/app.css";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    // The session cookie is HttpOnly (set by FastAPI), so the browser can't
    // read it directly. Ask the backend who we are; it validates the cookie.
    fetch(`${API_BASE}/api/auth/me`, { credentials: "include", cache: "no-store" })
      .then((r) => r.json())
      .then((body) => {
        if (!body?.user) {
          router.replace("/login");
        } else {
          setChecked(true);
        }
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  if (!checked) {
    return <div className="app-shell app-loading" />;
  }

  return <AppShell>{children}</AppShell>;
}