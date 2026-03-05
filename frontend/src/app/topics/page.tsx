"use client";

import { useState } from "react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { useTopics } from "@/lib/use-data";
import { entityTypeColor } from "@/lib/utils";
import { LayoutGrid, List, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

export default function TopicsPage() {
  const [view, setView] = useState<"grid" | "list">("grid");
  const { data: topics, isLoading } = useTopics();

  return (
    <>
      <Header title="Topics" />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {isLoading ? "Loading..." : `${(topics || []).length} active topics`}
            </p>
            <div className="flex items-center bg-muted rounded-lg p-1">
              <button
                onClick={() => setView("grid")}
                className={`p-1.5 rounded-md transition-all duration-200 ${view === "grid" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"}`}
              >
                <LayoutGrid className="w-4 h-4" />
              </button>
              <button
                onClick={() => setView("list")}
                className={`p-1.5 rounded-md transition-all duration-200 ${view === "list" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground"}`}
              >
                <List className="w-4 h-4" />
              </button>
            </div>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 text-primary animate-spin" />
            </div>
          ) : view === "grid" ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {(topics || []).map((t, i) => (
                <Link key={t.cluster_id} href={`/topics/${t.cluster_id}`}>
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: i * 0.05, duration: 0.4 }}
                  >
                    <Card hover>
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-base font-semibold text-foreground">{t.label}</h3>
                            {t.is_new && <Badge variant="new">NEW</Badge>}
                          </div>
                          <p className="text-xs text-muted-foreground mt-1">
                            {t.message_count} messages &middot; {t.channel_count} channels
                          </p>
                        </div>
                        <div
                          className="w-3 h-3 rounded-full shrink-0 mt-1"
                          style={{ backgroundColor: t.avg_sentiment > 0.2 ? "var(--positive)" : t.avg_sentiment < -0.2 ? "var(--negative)" : "var(--neutral-sentiment)" }}
                        />
                      </div>

                      <div className="mt-4">
                        <Sparkline data={t.sparkline} width={200} height={32} />
                      </div>

                      <div className="mt-3 flex items-center gap-1 flex-wrap">
                        {t.top_entities.slice(0, 3).map(e => (
                          <Badge key={e.id} variant="entity" color={entityTypeColor(e.type)} className="text-[10px]">
                            {e.text}
                          </Badge>
                        ))}
                      </div>

                      <p className="mt-2 text-xs text-muted-foreground">
                        Sentiment: {t.avg_sentiment.toFixed(2)}
                      </p>
                    </Card>
                  </motion.div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {(topics || []).map((t, i) => (
                <Link key={t.cluster_id} href={`/topics/${t.cluster_id}`}>
                  <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04, duration: 0.3 }}
                    whileHover={{ x: 4 }}
                    className="flex items-center justify-between bg-card rounded-lg border border-border px-5 py-3 hover:bg-accent transition-colors duration-200"
                  >
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-foreground">{t.label}</span>
                        {t.is_new && <Badge variant="new">NEW</Badge>}
                      </div>
                      <div className="flex items-center gap-1">
                        {t.top_entities.slice(0, 2).map(e => (
                          <Badge key={e.id} variant="entity" color={entityTypeColor(e.type)} className="text-[10px]">
                            {e.text}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-xs text-muted-foreground">{t.message_count} msgs</span>
                      <Sparkline data={t.sparkline} width={60} height={20} />
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: t.avg_sentiment > 0.2 ? "var(--positive)" : t.avg_sentiment < -0.2 ? "var(--negative)" : "var(--neutral-sentiment)" }}
                      />
                    </div>
                  </motion.div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </PageTransition>
    </>
  );
}
