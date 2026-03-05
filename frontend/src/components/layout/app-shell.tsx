"use client";

import { useState, createContext, useContext } from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "./sidebar";
import { motion } from "framer-motion";

interface SidebarCtx {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
}

const SidebarContext = createContext<SidebarCtx>({ collapsed: false, setCollapsed: () => {} });
export function useSidebar() { return useContext(SidebarContext); }

const NO_SHELL_PATHS = ["/login"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  if (NO_SHELL_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed }}>
      <div className="flex min-h-screen">
        <Sidebar />
        <motion.main
          animate={{ marginLeft: collapsed ? 64 : 240 }}
          transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
          className="flex-1 min-w-0"
        >
          {children}
        </motion.main>
      </div>
    </SidebarContext.Provider>
  );
}
