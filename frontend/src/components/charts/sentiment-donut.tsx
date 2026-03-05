"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

interface Props {
  breakdown: { positive: number; neutral: number; negative: number };
}

const COLORS = ["var(--positive)", "var(--neutral-sentiment)", "var(--negative)"];

export function SentimentDonutChart({ breakdown }: Props) {
  const data = [
    { name: "Positive", value: Math.round(breakdown.positive) },
    { name: "Neutral", value: Math.round(breakdown.neutral) },
    { name: "Negative", value: Math.round(breakdown.negative) },
  ];

  return (
    <ResponsiveContainer width="100%" height={180}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={75}
          dataKey="value"
          strokeWidth={2}
          stroke="var(--card)"
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i]} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
