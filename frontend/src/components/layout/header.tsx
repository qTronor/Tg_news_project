"use client";

import { useState, useRef, useEffect } from "react";
import { useTheme } from "next-themes";
import { motion, AnimatePresence } from "framer-motion";
import { Sun, Moon, Monitor, Clock, Activity, AlertTriangle, LogOut, Shield, Languages, Menu } from "lucide-react";
import { useGlobalTimeRange, useDemoContext } from "@/components/providers";
import { useAuth } from "@/components/auth/auth-provider";
import { useTranslation } from "@/lib/i18n";
import { useSidebar } from "./app-shell";
import type { RangePreset } from "@/lib/hooks";

const PRESETS: { value: RangePreset; label: string }[] = [
  { value: "1h", label: "1ч" },
  { value: "6h", label: "6ч" },
  { value: "24h", label: "24ч" },
  { value: "7d", label: "7д" },
  { value: "30d", label: "30д" },
];

export function Header({ title }: { title: string }) {
  const { theme, setTheme } = useTheme();
  const { preset, setRange } = useGlobalTimeRange();
  const { isDemo, setIsDemo, lastError } = useDemoContext();
  const { user, isAdmin, logout } = useAuth();
  const { locale, setLocale, t } = useTranslation();
  const { setMobileOpen } = useSidebar();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const themeOptions = [
    { value: "light", icon: Sun },
    { value: "dark", icon: Moon },
    { value: "system", icon: Monitor },
  ];

  return (
    <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md border-b border-border">
      <div className="h-16 flex items-center justify-between px-4 md:px-6 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="md:hidden p-1.5 -ml-1 text-muted-foreground hover:text-foreground rounded-lg hover:bg-accent transition-colors shrink-0"
          >
            <Menu className="w-5 h-5" />
          </button>
          <motion.h1
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-lg md:text-xl font-semibold text-foreground truncate"
          >
            {title}
          </motion.h1>
        </div>

        <div className="flex items-center gap-2 md:gap-3 shrink-0">
          <div className="hidden sm:flex items-center gap-1 bg-muted rounded-lg p-1">
            <Clock className="w-4 h-4 text-muted-foreground ml-2" />
            {PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => setRange(p.value)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
                  preset === p.value
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          <button
            onClick={() => setIsDemo(!isDemo)}
            className={`hidden sm:flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
              isDemo
                ? "bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20"
                : "bg-positive/10 text-positive border border-positive/20"
            }`}
          >
            <Activity className={`w-3.5 h-3.5 ${!isDemo ? "animate-pulse" : ""}`} />
            {isDemo ? t("header.demo") : t("header.live")}
          </button>

          <button
            onClick={() => setLocale(locale === "ru" ? "en" : "ru")}
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 bg-muted rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            title={locale === "ru" ? "Switch to English" : "Переключить на русский"}
          >
            <Languages className="w-3.5 h-3.5" />
            {locale === "ru" ? "EN" : "RU"}
          </button>

          <div className="hidden md:flex items-center bg-muted rounded-lg p-1">
            {themeOptions.map(opt => {
              const Icon = opt.icon;
              return (
                <button
                  key={opt.value}
                  onClick={() => setTheme(opt.value)}
                  className={`p-1.5 rounded-md transition-all duration-200 ${
                    theme === opt.value
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Icon className="w-4 h-4" />
                </button>
              );
            })}
          </div>

          {user && (
            <div className="relative" ref={menuRef}>
              <button
                onClick={() => setMenuOpen(!menuOpen)}
                className="flex items-center gap-2 px-3 py-1.5 bg-muted rounded-lg hover:bg-accent transition-colors"
              >
                <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center">
                  <span className="text-[10px] font-bold text-primary">
                    {user.username.charAt(0).toUpperCase()}
                  </span>
                </div>
                <span className="text-xs font-medium text-foreground hidden sm:inline">
                  {user.username}
                </span>
                {isAdmin && <Shield className="w-3 h-3 text-primary" />}
              </button>

              <AnimatePresence>
                {menuOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: -5, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -5, scale: 0.95 }}
                    transition={{ duration: 0.15 }}
                    className="absolute right-0 top-full mt-2 w-56 bg-card rounded-xl border border-border shadow-xl shadow-black/10 overflow-hidden z-50"
                  >
                    <div className="p-3 border-b border-border">
                      <p className="text-sm font-medium text-foreground">{user.username}</p>
                      <p className="text-xs text-muted-foreground">{user.email}</p>
                      <div className="flex items-center gap-1.5 mt-1">
                        {isAdmin ? (
                          <span className="text-[10px] font-semibold text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                            ADMIN
                          </span>
                        ) : (
                          <span className="text-[10px] font-semibold text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                            USER
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="p-1">
                      <button
                        onClick={() => { setMenuOpen(false); logout(); }}
                        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                      >
                        <LogOut className="w-4 h-4" />
                        {t("header.logout")}
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

      <AnimatePresence>
        {lastError && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-6 py-2 bg-destructive/10 border-t border-destructive/20 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-destructive">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                <span>{lastError}</span>
              </div>
              <button
                onClick={() => setIsDemo(true)}
                className="text-xs font-medium text-destructive hover:underline shrink-0"
              >
                {t("header.switchToDemo")}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
