"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { API_BASE } from "@/lib/config";
import { apiFetch } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import "@/styles/app.css";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    apiFetch(`${API_BASE}/api/auth/me`)
      .then((r) => r.json())
      .then((body) => {
        if (!body?.user) {
          if (typeof window !== "undefined") {
            localStorage.removeItem("token");
          }
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