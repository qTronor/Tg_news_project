"use client";

import { useState } from "react";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import { useTopics } from "@/lib/use-data";
import { entityTypeColor } from "@/lib/utils";
import { LayoutGrid, List, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

export default function TopicsPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<"grid" | "list">("grid");
  const { data: topics, isLoading } = useTopics();

  return (
    <>
      <Header title={t("topics.title")} />
      <PageTransition>
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {isLoading ? t("common.loading") : `${(topics || []).length} ${t("topics.activeTopics")}`}
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
              {(topics || []).map((topic, i) => (
                <Link key={topic.cluster_id} href={`/topics/${topic.cluster_id}`}>
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: i * 0.05, duration: 0.4 }}
                  >
                    <Card hover>
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-base font-semibold text-foreground">{topic.label}</h3>
                            {topic.is_new && <Badge variant="new">NEW</Badge>}
                            {topic.source_status && <SourceStatusBadge status={topic.source_status} />}
                          </div>
                          <p className="text-xs text-muted-foreground mt-1">
                            {topic.message_count} {t("topics.messages")} &middot; {topic.channel_count} {t("topics.channels")}
                          </p>
                        </div>
                        <div
                          className="w-3 h-3 rounded-full shrink-0 mt-1"
                          style={{ backgroundColor: topic.avg_sentiment > 0.2 ? "var(--positive)" : topic.avg_sentiment < -0.2 ? "var(--negative)" : "var(--neutral-sentiment)" }}
                        />
                      </div>

                      <div className="mt-4">
                        <Sparkline data={topic.sparkline} width={200} height={32} />
                      </div>

                      <div className="mt-3 flex items-center gap-1 flex-wrap">
                        {topic.top_entities.slice(0, 3).map(e => (
                          <Badge key={e.id} variant="entity" color={entityTypeColor(e.type)} className="text-[10px]">
                            {e.text}
                          </Badge>
                        ))}
                      </div>

                      <p className="mt-2 text-xs text-muted-foreground">
                        {t("topics.sentiment")}: {topic.avg_sentiment.toFixed(2)}
                      </p>
                    </Card>
                  </motion.div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {(topics || []).map((topic, i) => (
                <Link key={topic.cluster_id} href={`/topics/${topic.cluster_id}`}>
                  <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04, duration: 0.3 }}
                    whileHover={{ x: 4 }}
                    className="flex items-center justify-between bg-card rounded-lg border border-border px-5 py-3 hover:bg-accent transition-colors duration-200"
                  >
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-foreground">{topic.label}</span>
                        {topic.is_new && <Badge variant="new">NEW</Badge>}
                        {topic.source_status && <SourceStatusBadge status={topic.source_status} />}
                      </div>
                      <div className="flex items-center gap-1">
                        {topic.top_entities.slice(0, 2).map(e => (
                          <Badge key={e.id} variant="entity" color={entityTypeColor(e.type)} className="text-[10px]">
                            {e.text}
                          </Badge>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-xs text-muted-foreground">{topic.message_count} {t("common.msgs")}</span>
                      <Sparkline data={topic.sparkline} width={60} height={20} />
                      <div
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: topic.avg_sentiment > 0.2 ? "var(--positive)" : topic.avg_sentiment < -0.2 ? "var(--negative)" : "var(--neutral-sentiment)" }}
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
