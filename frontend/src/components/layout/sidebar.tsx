"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, Newspaper, Layers, Users, Share2, Settings,
  ChevronLeft, ChevronRight, Zap, Radio, ScrollText, Shield, X, CirclePlus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "./app-shell";
import { useAuth } from "@/components/auth/auth-provider";
import { useTranslation, type TranslationKey } from "@/lib/i18n";

const NAV_ITEMS: { href: string; labelKey: TranslationKey; icon: typeof LayoutDashboard }[] = [
  { href: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/feed", labelKey: "nav.feed", icon: Newspaper },
  { href: "/topics", labelKey: "nav.topics", icon: Layers },
  { href: "/entities", labelKey: "nav.entities", icon: Users },
  { href: "/graph", labelKey: "nav.graph", icon: Share2 },
  { href: "/sources", labelKey: "nav.sources", icon: CirclePlus },
  { href: "/settings", labelKey: "nav.settings", icon: Settings },
];

const ADMIN_ITEMS: { href: string; labelKey: TranslationKey; icon: typeof LayoutDashboard }[] = [
  { href: "/admin/channels", labelKey: "nav.channels", icon: Radio },
  { href: "/admin/audit-log", labelKey: "nav.audit", icon: ScrollText },
];

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, setCollapsed, mobileOpen, setMobileOpen } = useSidebar();
  const { isAdmin } = useAuth();
  const { t } = useTranslation();

  const items = isAdmin ? [...NAV_ITEMS, ...ADMIN_ITEMS] : NAV_ITEMS;

  return (
    <motion.aside
      initial={false}
      animate={{ width: collapsed ? 64 : 240 }}
      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      className={cn(
        "fixed left-0 top-0 z-40 h-screen flex flex-col border-r border-border bg-sidebar overflow-hidden",
        "max-md:w-60 max-md:transition-transform max-md:duration-300",
        mobileOpen ? "max-md:translate-x-0" : "max-md:-translate-x-full"
      )}
    >
      <div className="flex items-center gap-3 px-4 h-16 border-b border-border shrink-0">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
          <Zap className="w-4 h-4 text-primary-foreground" />
        </div>
        <AnimatePresence>
          {!collapsed && (
            <motion.span
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              className="font-semibold text-sm text-foreground whitespace-nowrap"
            >
              TG News Analytics
            </motion.span>
          )}
        </AnimatePresence>
        <button
          onClick={() => setMobileOpen(false)}
          className="ml-auto md:hidden p-1 text-muted-foreground hover:text-foreground"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      <nav className="flex-1 py-4 px-2 space-y-1 overflow-y-auto">
        {items.map((item, idx) => {
          const isFirstAdmin = idx === NAV_ITEMS.length && isAdmin;
          const isActive = item.href === "/"
            ? pathname === "/"
            : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <div key={item.href}>
              {isFirstAdmin && (
                <div className="my-3 px-3">
                  <div className="border-t border-border" />
                  <AnimatePresence>
                    {!collapsed && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center gap-1.5 mt-2 mb-1 px-1"
                      >
                        <Shield className="w-3 h-3 text-primary" />
                        <span className="text-[10px] font-semibold text-primary uppercase tracking-wider">
                          {t("nav.admin")}
                        </span>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )}
              <Link href={item.href}>
                <motion.div
                  whileHover={{ scale: 1.02, x: 2 }}
                  whileTap={{ scale: 0.98 }}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-200 relative",
                    isActive
                      ? "bg-sidebar-accent text-primary"
                      : "text-sidebar-foreground hover:bg-accent hover:text-foreground"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="nav-indicator"
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full"
                      transition={{ type: "spring", stiffness: 500, damping: 30 }}
                    />
                  )}
                  <Icon className="w-5 h-5 shrink-0" />
                  <AnimatePresence>
                    {!collapsed && (
                      <motion.span
                        initial={{ opacity: 0, width: 0 }}
                        animate={{ opacity: 1, width: "auto" }}
                        exit={{ opacity: 0, width: 0 }}
                        transition={{ duration: 0.2 }}
                        className="whitespace-nowrap overflow-hidden"
                      >
                        {t(item.labelKey)}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </motion.div>
              </Link>
            </div>
          );
        })}
      </nav>

      <div className="p-2 border-t border-border shrink-0">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center w-full py-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors duration-200"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>
    </motion.aside>
  );
}
