"use client";

import { useState, createContext, useContext } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./sidebar";
import { cn } from "@/lib/utils";

interface SidebarCtx {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

const SidebarContext = createContext<SidebarCtx>({
  collapsed: false,
  setCollapsed: () => {},
  mobileOpen: false,
  setMobileOpen: () => {},
});
export function useSidebar() { return useContext(SidebarContext); }

const NO_SHELL_PATHS = ["/login", "/forgot-password", "/reset-password"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (NO_SHELL_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  return <ShellLayout key={pathname}>{children}</ShellLayout>;
}

function ShellLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed, mobileOpen, setMobileOpen }}>
      <div className="flex min-h-screen">
        <Sidebar />
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/50 md:hidden"
            onClick={() => setMobileOpen(false)}
          />
        )}
        <main
          className={cn(
            "flex-1 min-w-0 transition-[margin-left] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]",
            "ml-0",
            collapsed ? "md:ml-16" : "md:ml-60"
          )}
        >
          {children}
        </main>
      </div>
    </SidebarContext.Provider>
  );
}
