"use client";

import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { SentimentPoint } from "@/types";
import { format, parseISO } from "date-fns";

interface Props {
  data: SentimentPoint[];
}

export function SentimentAreaChart({ data }: Props) {
  const formatted = data.map(d => ({
    ...d,
    label: format(parseISO(d.time), "HH:mm"),
  }));

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
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
        <Tooltip
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
