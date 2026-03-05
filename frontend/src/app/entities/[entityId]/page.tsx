"use client";

import { use } from "react";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useEntities, useTopics, useMessages } from "@/lib/use-data";
import { entityTypeColor, formatNumber } from "@/lib/utils";
import { ArrowLeft, Share2, TrendingUp, TrendingDown, Minus, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

export default function EntityDetailPage({ params }: { params: Promise<{ entityId: string }> }) {
  const { t } = useTranslation();
  const { entityId } = use(params);
  const { data: allEntities, isLoading: loadingEntities } = useEntities();
  const { data: allTopics } = useTopics();
  const { data: allMessages } = useMessages();

  const entity = (allEntities || []).find(e => e.id === entityId) || (allEntities || [])[0];

  if (loadingEntities || !entity) {
    return (
      <>
        <Header title={t("entities.title")} />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      </>
    );
  }

  const relatedTopics = (allTopics || []).filter(t =>
    t.top_entities.some(e => e.text === entity.text)
  );
  const relatedMessages = (allMessages || []).filter(m =>
    m.entities?.some(e => e.text === entity.text)
  ).slice(0, 5);

  const trendPct = entity.trend_pct || 0;
  const TrendIcon = trendPct > 0 ? TrendingUp : trendPct < 0 ? TrendingDown : Minus;
  const trendColor = trendPct > 0 ? "text-positive" : trendPct < 0 ? "text-negative" : "text-muted-foreground";

  return (
    <>
      <Header title={`${t("entities.title")}: ${entity.text}`} />
      <PageTransition>
        <div className="p-6 space-y-6">
          <div className="flex items-center justify-between">
            <Link href="/entities" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
              <ArrowLeft className="w-4 h-4" />
              {t("entities.backToEntities")}
            </Link>
            <Link href={`/graph?focus=ent-${entityId}`}>
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="flex items-center gap-1.5 px-3 py-2 bg-muted rounded-lg text-sm text-foreground hover:bg-accent transition-colors"
              >
                <Share2 className="w-4 h-4" />
                {t("entities.viewInGraph")}
              </motion.button>
            </Link>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-card rounded-xl border border-border p-6"
          >
            <div className="flex items-center gap-3">
              <Badge variant="entity" color={entityTypeColor(entity.type)} className="text-base px-3 py-1">
                {entity.type}
              </Badge>
              <h2 className="text-2xl font-bold text-foreground">{entity.text}</h2>
            </div>
            {entity.normalized && (
              <p className="text-sm text-muted-foreground mt-2">{entity.normalized}</p>
            )}
            <div className="grid grid-cols-4 gap-4 mt-4">
              <div>
                <p className="text-xs text-muted-foreground">{t("entities.mentions")}</p>
                <p className="text-xl font-bold text-foreground">{formatNumber(entity.mention_count || 0)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("entities.topics")}</p>
                <p className="text-xl font-bold text-foreground">{entity.topic_count || 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("entities.channels")}</p>
                <p className="text-xl font-bold text-foreground">{entity.channel_count || 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">{t("entities.trend")}</p>
                <div className={`text-xl font-bold flex items-center gap-1 ${trendColor}`}>
                  <TrendIcon className="w-5 h-5" />
                  {trendPct > 0 ? "+" : ""}{trendPct}%
                </div>
              </div>
            </div>
          </motion.div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader><CardTitle>{t("entities.relatedTopics")}</CardTitle></CardHeader>
              <div className="space-y-2">
                {relatedTopics.length > 0 ? relatedTopics.map(topic => (
                  <Link key={topic.cluster_id} href={`/topics/${topic.cluster_id}`}>
                    <motion.div
                      whileHover={{ x: 4 }}
                      className="flex items-center justify-between py-2 px-2 rounded-lg hover:bg-accent transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-foreground">{topic.label}</span>
                        {topic.is_new && <Badge variant="new">NEW</Badge>}
                      </div>
                      <span className="text-xs text-muted-foreground">{topic.message_count} {t("common.msgs")}</span>
                    </motion.div>
                  </Link>
                )) : (
                  <p className="text-sm text-muted-foreground">{t("entities.noRelatedTopics")}</p>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader><CardTitle>{t("entities.recentMentions")}</CardTitle></CardHeader>
              <div className="space-y-2">
                {relatedMessages.length > 0 ? relatedMessages.map(m => (
                  <div key={m.event_id} className="border-b border-border pb-2 last:border-0">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">{m.channel}</span>
                    </div>
                    <p className="text-sm text-foreground mt-1 line-clamp-2">{m.text}</p>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground">{t("entities.noRecentMentions")}</p>
                )}
              </div>
            </Card>
          </div>
        </div>
      </PageTransition>
    </>
  );
}
