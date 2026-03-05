"use client";

import { useState, useCallback, useMemo } from "react";
import { subHours, subDays, formatISO } from "date-fns";

export type RangePreset = "1h" | "6h" | "24h" | "7d" | "30d" | "custom";

export function useTimeRange(initial: RangePreset = "24h") {
  const [preset, setPreset] = useState<RangePreset>(initial);
  const [customFrom, setCustomFrom] = useState<string>("");
  const [customTo, setCustomTo] = useState<string>("");

  const range = useMemo(() => {
    const now = new Date();
    if (preset === "custom" && customFrom && customTo) {
      return { from: customFrom, to: customTo };
    }
    const map: Record<string, Date> = {
      "1h": subHours(now, 1),
      "6h": subHours(now, 6),
      "24h": subDays(now, 1),
      "7d": subDays(now, 7),
      "30d": subDays(now, 30),
    };
    return {
      from: formatISO(map[preset] || subDays(now, 1)),
      to: formatISO(now),
    };
  }, [preset, customFrom, customTo]);

  const setRange = useCallback((p: RangePreset, from?: string, to?: string) => {
    setPreset(p);
    if (from) setCustomFrom(from);
    if (to) setCustomTo(to);
  }, []);

  return { preset, range, setRange };
}

export function useDemoMode() {
  const [isDemo, setIsDemo] = useState(true);
  return { isDemo, setIsDemo };
}
