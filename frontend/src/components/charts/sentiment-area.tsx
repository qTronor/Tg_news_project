"use client";

import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { SentimentPoint } from "@/types";
import { format, isSameDay, parseISO } from "date-fns";
import type { RangePreset } from "@/lib/hooks";

interface Props {
  data: SentimentPoint[];
  preset?: RangePreset;
  from?: string;
  to?: string;
}

function resolveTicks(preset: RangePreset, fromDate: Date, toDate: Date) {
  const start = fromDate.getTime();
  const end = toDate.getTime();
  if (end <= start) return [start, end];

  const stepMs = (() => {
    switch (preset) {
      case "1h":
        return 15 * 60_000;
      case "6h":
        return 30 * 60_000;
      case "24h":
        return 60 * 60_000;
      case "7d":
      case "30d":
        return 24 * 60 * 60_000;
      default: {
        const duration = end - start;
        if (duration <= 6 * 60 * 60_000) return 30 * 60_000;
        if (duration <= 24 * 60 * 60_000) return 60 * 60_000;
        return 24 * 60 * 60_000;
      }
    }
  })();

  const ticks: number[] = [];
  for (let value = start; value < end; value += stepMs) {
    ticks.push(value);
  }
  if (ticks.length === 0 || ticks[ticks.length - 1] !== end) {
    ticks.push(end);
  }
  return ticks;
}

function formatTick(ts: number, preset: RangePreset, toDate: Date) {
  const value = new Date(ts);
  switch (preset) {
    case "1h":
    case "6h":
    case "24h":
      return format(value, "HH:mm");
    case "7d":
      return format(value, "EEE dd");
    case "30d":
      return isSameDay(value, toDate) ? `Today ${format(value, "dd")}` : format(value, "dd MMM");
    default:
      return format(value, "dd MMM HH:mm");
  }
}

function formatTooltipLabel(ts: number, preset: RangePreset) {
  const value = new Date(ts);
  if (preset === "7d" || preset === "30d") {
    return format(value, "dd MMM yyyy");
  }
  return format(value, "dd MMM yyyy HH:mm");
}

export function SentimentAreaChart({ data, preset = "24h", from, to }: Props) {
  const safeFrom = from ? parseISO(from) : data[0] ? parseISO(data[0].time) : new Date();
  const safeTo = to ? parseISO(to) : data[data.length - 1] ? parseISO(data[data.length - 1].time) : new Date();

  const formatted = data.map((d) => ({
    ...d,
    ts: parseISO(d.time).getTime(),
  }));
  const ticks = resolveTicks(preset, safeFrom, safeTo);

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={formatted} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="gradPos" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--positive)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--positive)" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradNeu" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--neutral-sentiment)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--neutral-sentiment)" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradNeg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--negative)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--negative)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          type="number"
          dataKey="ts"
          domain={[safeFrom.getTime(), safeTo.getTime()]}
          ticks={ticks}
          tickFormatter={(value) => formatTick(value, preset, safeTo)}
          tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
          minTickGap={16}
          tickLine={false}
          axisLine={false}
        />
        <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
        <Tooltip
          labelFormatter={(value) => formatTooltipLabel(Number(value), preset)}
          contentStyle={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          }}
        />
        <Area type="monotone" dataKey="positive" stroke="var(--positive)" fill="url(#gradPos)" strokeWidth={2} />
        <Area type="monotone" dataKey="neutral" stroke="var(--neutral-sentiment)" fill="url(#gradNeu)" strokeWidth={2} />
        <Area type="monotone" dataKey="negative" stroke="var(--negative)" fill="url(#gradNeg)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
