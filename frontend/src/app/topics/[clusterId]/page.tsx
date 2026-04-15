"use client";

import { use } from "react";
import { useTranslation } from "@/lib/i18n";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MessageCard } from "@/components/feed/message-card";
import { SourcePanel } from "@/components/topics/source-panel";
import { VolumeLineChart } from "@/components/charts/volume-line";
import { ChannelBarChart } from "@/components/charts/channel-bar";
import { SentimentDonutChart } from "@/components/charts/sentiment-donut";
import { useTopicDetail } from "@/lib/use-data";
import { entityTypeColor, formatNumber } from "@/lib/utils";
import { ArrowLeft, Download, Share2, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

export default function TopicDetailPage({ params }: { params: Promise<{ clusterId: string }> }) {
  const { t } = useTranslation();
  const { clusterId } = use(params);
  const { data: detail, isLoading } = useTopicDetail(clusterId);

  if (isLoading || !detail) {
    return (
      <>
        <Header title={t("topics.title")} />
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      </>
    );
  }

  return (
    <>
      <Header title={detail.label} />
      <PageTransition>
        <div className="p-6 space-y-6">
          <div className="flex items-center justify-between">
            <Link href="/topics" className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
              <ArrowLeft className="w-4 h-4" />
              {t("topics.backToTopics")}
            </Link>
            <div className="flex items-center gap-2">
              <Link href={`/graph?mode=propagation&clusterId=${encodeURIComponent(clusterId)}`}>
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  className="flex items-center gap-1.5 px-3 py-2 bg-muted rounded-lg text-sm text-foreground hover:bg-accent transition-colors"
                >
                  <Share2 className="w-4 h-4" />
                  {t("topics.viewInGraph")}
                </motion.button>
              </Link>
              <motion.button
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="flex items-center gap-1.5 px-3 py-2 bg-muted rounded-lg text-sm text-foreground hover:bg-accent transition-colors"
              >
                <Download className="w-4 h-4" />
                {t("topics.export")}
              </motion.button>
            </div>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-card rounded-xl border border-border p-6"
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-2xl font-bold text-foreground">{detail.label}</h2>
                  {detail.is_new && <Badge variant="new">NEW</Badge>}
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {detail.message_count} {t("topics.messages")} &middot; {detail.channel_count} {t("topics.channels")} &middot; {t("topics.avgSentiment")}: {detail.avg_sentiment.toFixed(2)}
                </p>
              </div>
            </div>
          </motion.div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader><CardTitle>{t("topics.messageVolume")}</CardTitle></CardHeader>
              <VolumeLineChart data={detail.volume_timeline} />
            </Card>
            <Card>
              <CardHeader><CardTitle>{t("topics.channelDistribution")}</CardTitle></CardHeader>
              <ChannelBarChart data={detail.channels} />
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card>
              <CardHeader><CardTitle>{t("topics.keyEntities")}</CardTitle></CardHeader>
              <div className="space-y-2">
                {detail.top_entities.map(e => (
                  <Link key={e.id} href={`/entities/${e.id}`}>
                    <div className="flex items-center justify-between py-1.5 hover:bg-accent rounded-lg px-2 transition-colors">
                      <div className="flex items-center gap-2">
                        <Badge variant="entity" color={entityTypeColor(e.type)}>{e.type}</Badge>
                        <span className="text-sm text-foreground">{e.text}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">{formatNumber(e.mention_count || 0)}</span>
                    </div>
                  </Link>
                ))}
              </div>
            </Card>

            <Card>
              <CardHeader><CardTitle>{t("topics.sentiment")}</CardTitle></CardHeader>
              <SentimentDonutChart breakdown={detail.sentiment_breakdown} />
              <div className="flex items-center justify-center gap-4 mt-2 text-xs">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-positive" /> {t("sentiment.positive")}</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-neutral-sentiment" /> {t("sentiment.neutral")}</span>
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-negative" /> {t("sentiment.negative")}</span>
              </div>
            </Card>

            <Card>
              <CardHeader><CardTitle>{t("topics.relatedTopics")}</CardTitle></CardHeader>
              <div className="space-y-2">
                {detail.related_topics.map(rt => (
                  <Link key={rt.cluster_id} href={`/topics/${rt.cluster_id}`}>
                    <motion.div
                      whileHover={{ x: 4 }}
                      className="flex items-center justify-between py-2 px-2 rounded-lg hover:bg-accent transition-colors"
                    >
                      <span className="text-sm text-foreground">{rt.label}</span>
                      <span className="text-xs text-muted-foreground">sim: {rt.similarity}</span>
                    </motion.div>
                  </Link>
                ))}
              </div>
            </Card>
          </div>

          <SourcePanel source={detail.first_source} />

          <Card>
            <CardHeader>
              <CardTitle>{t("topics.representativeMessages")}</CardTitle>
            </CardHeader>
            <div className="space-y-3">
              {detail.representative_messages.map((msg, i) => (
                <MessageCard key={msg.event_id} message={msg} index={i} />
              ))}
            </div>
          </Card>
        </div>
      </PageTransition>
    </>
  );
}
