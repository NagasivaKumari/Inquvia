"use client";

import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { AppHeader } from "@/components/layout/AppHeader";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="app-shell">
      {navOpen && (
        <button
          type="button"
          className="app-nav-backdrop"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      )}
      <Sidebar open={navOpen} onNavigate={() => setNavOpen(false)} />
      <div className="app-main">
        <AppHeader onMenu={() => setNavOpen(true)} />
        <main>{children}</main>
      </div>
    </div>
  );
}
