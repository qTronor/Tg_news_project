"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, createContext, useContext, useCallback } from "react";
import { useTimeRange, type RangePreset } from "@/lib/hooks";

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

export function Providers({ children }: { children: React.ReactNode }) {
  const timeRange = useTimeRange("24h");
  const [isDemo, setIsDemoRaw] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);

  const setIsDemo = useCallback((v: boolean) => {
    setIsDemoRaw(v);
    setLastError(null);
    queryClient.clear();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
        <DemoContext.Provider value={{ isDemo, setIsDemo, lastError, setLastError }}>
          <TimeRangeContext.Provider value={timeRange}>
            {children}
          </TimeRangeContext.Provider>
        </DemoContext.Provider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
