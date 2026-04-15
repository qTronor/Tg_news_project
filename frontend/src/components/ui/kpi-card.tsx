"use client";

import { motion } from "framer-motion";
import { cn, formatNumber } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface KpiCardProps {
  title: string;
  value: number | string;
  change?: number;
  icon: React.ReactNode;
  delay?: number;
}

export function KpiCard({ title, value, change, icon, delay = 0 }: KpiCardProps) {
  const formatted = typeof value === "number" ? formatNumber(value) : value;
  const trendIcon =
    change === undefined ? null :
    change > 0 ? <TrendingUp className="w-3.5 h-3.5" /> :
    change < 0 ? <TrendingDown className="w-3.5 h-3.5" /> :
    <Minus className="w-3.5 h-3.5" />;

  const trendColor =
    change === undefined ? "" :
    change > 0 ? "text-positive" :
    change < 0 ? "text-negative" :
    "text-muted-foreground";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.4, 0, 0.2, 1] }}
      className="bg-card rounded-xl border border-border p-5 flex items-start gap-4"
    >
      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-muted-foreground font-medium truncate">{title}</p>
        <p className="text-2xl font-bold text-foreground mt-1">{formatted}</p>
        {change !== undefined && (
          <div className={cn("flex items-center gap-1 mt-1 text-xs font-medium", trendColor)}>
            {trendIcon}
            <span>{change > 0 ? "+" : ""}{change}%</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}
