"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, createContext, useContext, useCallback, useEffect } from "react";
import { useTimeRange, type RangePreset } from "@/lib/hooks";
import { AuthProvider } from "@/components/auth/auth-provider";
import { I18nContext, getTranslator, type Locale } from "@/lib/i18n";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

interface TimeRangeCtx {
  preset: RangePreset;
  range: { from: string; to: string };
  setRange: (p: RangePreset, from?: string, to?: string) => void;
}

const TimeRangeContext = createContext<TimeRangeCtx | null>(null);

export function useGlobalTimeRange() {
  const ctx = useContext(TimeRangeContext);
  if (!ctx) throw new Error("useGlobalTimeRange must be used within Providers");
  return ctx;
}

interface DemoCtx {
  isDemo: boolean;
  setIsDemo: (v: boolean) => void;
  lastError: string | null;
  setLastError: (e: string | null) => void;
}
const DemoContext = createContext<DemoCtx>({
  isDemo: true,
  setIsDemo: () => {},
  lastError: null,
  setLastError: () => {},
});
export function useDemoContext() {
  return useContext(DemoContext);
}

const LOCALE_KEY = "tg_locale";

export function Providers({ children }: { children: React.ReactNode }) {
  const timeRange = useTimeRange("24h");
  const [isDemo, setIsDemoRaw] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);
  const [locale, setLocaleRaw] = useState<Locale>("ru");

  useEffect(() => {
    const stored = localStorage.getItem(LOCALE_KEY) as Locale | null;
    if (stored === "en" || stored === "ru") setLocaleRaw(stored);
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleRaw(l);
    localStorage.setItem(LOCALE_KEY, l);
    document.documentElement.lang = l;
  }, []);

  const t = getTranslator(locale);

  const setIsDemo = useCallback((v: boolean) => {
    setIsDemoRaw(v);
    setLastError(null);
    queryClient.clear();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
        <I18nContext.Provider value={{ locale, setLocale, t }}>
          <AuthProvider>
            <DemoContext.Provider value={{ isDemo, setIsDemo, lastError, setLastError }}>
              <TimeRangeContext.Provider value={timeRange}>
                {children}
              </TimeRangeContext.Provider>
            </DemoContext.Provider>
          </AuthProvider>
        </I18nContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
