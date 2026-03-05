"use client";

import { useState } from "react";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Badge } from "@/components/ui/badge";
import { useEntities } from "@/lib/use-data";
import { formatNumber, entityTypeColor } from "@/lib/utils";
import { Search, TrendingUp, TrendingDown, Minus, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

const TYPES = ["All", "PER", "ORG", "LOC", "MISC"];

export default function EntitiesPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("All");

  const { data: allEntities, isLoading } = useEntities();

  const filtered = (allEntities || []).filter(e => {
    if (search && !e.text.toLowerCase().includes(search.toLowerCase())) return false;
    if (typeFilter !== "All" && e.type !== typeFilter) return false;
    return true;
  });

  return (
    <>
      <Header title={t("entities.title")} />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder={t("entities.search")}
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-card border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-primary/30 transition-all duration-200"
              />
            </div>
            <div className="flex items-center bg-muted rounded-lg p-1">
              {TYPES.map(t => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200 ${
                    typeFilter === t
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
            </div>
          ) : (
            <div className="bg-card rounded-xl border border-border overflow-hidden">
              <div className="grid grid-cols-7 px-5 py-3 border-b border-border text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                <div className="col-span-2">{t("entities.entity")}</div>
                <div>{t("entities.type")}</div>
                <div className="text-right">{t("entities.mentions")}</div>
                <div className="text-right">{t("entities.topics")}</div>
                <div className="text-right">{t("entities.channels")}</div>
                <div className="text-right">{t("entities.trend")}</div>
              </div>
              {filtered.map((e, i) => {
                const trendPct = e.trend_pct || 0;
                const TrendIcon = trendPct > 0 ? TrendingUp : trendPct < 0 ? TrendingDown : Minus;
                const trendColor = trendPct > 0 ? "text-positive" : trendPct < 0 ? "text-negative" : "text-muted-foreground";

                return (
                  <Link key={e.id} href={`/entities/${e.id}`}>
                    <motion.div
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.03, duration: 0.3 }}
                      whileHover={{ backgroundColor: "var(--accent)" }}
                      className="grid grid-cols-7 px-5 py-3 border-b border-border items-center transition-colors duration-200 cursor-pointer"
                    >
                      <div className="col-span-2 text-sm font-medium text-foreground">{e.text}</div>
                      <div><Badge variant="entity" color={entityTypeColor(e.type)}>{e.type}</Badge></div>
                      <div className="text-right text-sm text-foreground">{formatNumber(e.mention_count || 0)}</div>
                      <div className="text-right text-sm text-muted-foreground">{e.topic_count || 0}</div>
                      <div className="text-right text-sm text-muted-foreground">{e.channel_count || 0}</div>
                      <div className={`text-right flex items-center justify-end gap-1 text-sm ${trendColor}`}>
                        <TrendIcon className="w-3.5 h-3.5" />
                        {trendPct > 0 ? "+" : ""}{trendPct}%
                      </div>
                    </motion.div>
                  </Link>
                );
              })}
              {filtered.length === 0 && (
                <p className="text-center text-muted-foreground py-8">{t("entities.noEntities")}</p>
              )}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
