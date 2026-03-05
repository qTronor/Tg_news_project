"use client";

import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { KpiCard } from "@/components/ui/kpi-card";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { SentimentAreaChart } from "@/components/charts/sentiment-area";
import { ChannelBarChart } from "@/components/charts/channel-bar";
import { useOverview, useTopics, useEntities, useSentiment } from "@/lib/use-data";
import { formatNumber, entityTypeColor } from "@/lib/utils";
import { useTranslation } from "@/lib/i18n";
import { MessageSquare, Layers, Radio, TrendingUp, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <Loader2 className="w-6 h-6 text-primary animate-spin" />
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const { data: overview, isLoading: loadingOverview } = useOverview();
  const { data: topics, isLoading: loadingTopics } = useTopics();
  const { data: entities, isLoading: loadingEntities } = useEntities();
  const { data: sentiment, isLoading: loadingSentiment } = useSentiment();

  const topEntities = (entities || []).slice(0, 8);

  const allChannels = (topics || []).flatMap(t => t.channels);
  const channelAgg = Object.values(
    allChannels.reduce<Record<string, { channel: string; count: number }>>((acc, c) => {
      if (!acc[c.channel]) acc[c.channel] = { channel: c.channel, count: 0 };
      acc[c.channel].count += c.count;
      return acc;
    }, {})
  );

  return (
    <>
      <Header title="Dashboard" />
      <PageTransition>
        <div className="p-6 space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {loadingOverview || !overview ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="bg-card rounded-xl border border-border p-5 h-28 animate-pulse" />
              ))
            ) : (
              <>
                <KpiCard
                  title={t("dash.messagesToday")}
                  value={overview.total_messages}
                  change={overview.messages_change_pct}
                  icon={<MessageSquare className="w-5 h-5" />}
                  delay={0}
                />
                <KpiCard
                  title={t("dash.newTopics")}
                  value={overview.new_topics}
                  change={overview.topics_change}
                  icon={<Layers className="w-5 h-5" />}
                  delay={0.1}
                />
                <KpiCard
                  title={t("dash.activeChannels")}
                  value={overview.active_channels}
                  icon={<Radio className="w-5 h-5" />}
                  delay={0.2}
                />
                <KpiCard
                  title={t("dash.avgSentiment")}
                  value={overview.avg_sentiment.toFixed(2)}
                  icon={<TrendingUp className="w-5 h-5" />}
                  delay={0.3}
                />
              </>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("dash.sentimentDynamics")}</CardTitle>
              </CardHeader>
              {loadingSentiment || !sentiment ? <LoadingSpinner /> : <SentimentAreaChart data={sentiment} />}
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("dash.topEntities")}</CardTitle>
              </CardHeader>
              {loadingEntities ? <LoadingSpinner /> : (
                <div className="space-y-3">
                  {topEntities.map((e, i) => (
                    <motion.div
                      key={e.id}
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.05 * i, duration: 0.3 }}
                      className="flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground w-5">{i + 1}.</span>
                        <Badge variant="entity" color={entityTypeColor(e.type)}>{e.type}</Badge>
                        <Link href={`/entities/${e.id}`} className="text-sm text-foreground hover:text-primary transition-colors">
                          {e.text}
                        </Link>
                      </div>
                      <span className="text-xs text-muted-foreground">{formatNumber(e.mention_count || 0)}</span>
                    </motion.div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle>{t("dash.topTopics")}</CardTitle>
              </CardHeader>
              {loadingTopics ? <LoadingSpinner /> : (
                <div className="space-y-3">
                  {(topics || []).map((t, i) => (
                    <Link key={t.cluster_id} href={`/topics/${t.cluster_id}`}>
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.05 * i, duration: 0.3 }}
                        whileHover={{ x: 4 }}
                        className="flex items-center justify-between p-3 rounded-lg hover:bg-accent transition-colors duration-200 group"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="flex flex-col min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-foreground truncate">{t.label}</span>
                              {t.is_new && <Badge variant="new">NEW</Badge>}
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {t.message_count} msgs &middot; {t.channel_count} channels
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <Sparkline data={t.sparkline} width={80} height={24} />
                          <div
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: t.avg_sentiment > 0.2 ? "var(--positive)" : t.avg_sentiment < -0.2 ? "var(--negative)" : "var(--neutral-sentiment)" }}
                          />
                        </div>
                      </motion.div>
                    </Link>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("dash.channelActivity")}</CardTitle>
              </CardHeader>
              {loadingTopics ? <LoadingSpinner /> : <ChannelBarChart data={channelAgg} />}
            </Card>
          </div>
        </div>
      </PageTransition>
    </>
  );
}
