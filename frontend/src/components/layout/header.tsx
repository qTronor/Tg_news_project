"use client";

import { useTheme } from "next-themes";
import { motion, AnimatePresence } from "framer-motion";
import { Sun, Moon, Monitor, Clock, Activity, AlertTriangle } from "lucide-react";
import { useGlobalTimeRange, useDemoContext } from "@/components/providers";
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

  const themeOptions = [
    { value: "light", icon: Sun },
    { value: "dark", icon: Moon },
    { value: "system", icon: Monitor },
  ];

  return (
    <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md border-b border-border">
      <div className="h-16 flex items-center justify-between px-6">
        <motion.h1
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-xl font-semibold text-foreground"
        >
          {title}
        </motion.h1>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
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
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
              isDemo
                ? "bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20"
                : "bg-positive/10 text-positive border border-positive/20"
            }`}
          >
            <Activity className={`w-3.5 h-3.5 ${!isDemo ? "animate-pulse" : ""}`} />
            {isDemo ? "Demo" : "Live"}
          </button>

          <div className="flex items-center bg-muted rounded-lg p-1">
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
                Switch to Demo
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
