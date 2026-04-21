"use client";

import { use, type ReactNode } from "react";
import { format, parseISO } from "date-fns";
import { motion } from "framer-motion";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  CircleDot,
  Download,
  Gauge,
  GitBranch,
  Hash,
  Loader2,
  Network,
  Radio,
  Share2,
  ShieldCheck,
  Split,
  TrendingUp,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MessageCard } from "@/components/feed/message-card";
import { SourcePanel } from "@/components/topics/source-panel";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import { VolumeLineChart } from "@/components/charts/volume-line";
import { ChannelBarChart } from "@/components/charts/channel-bar";
import { SentimentDonutChart } from "@/components/charts/sentiment-donut";
import { useTopicDetail } from "@/lib/use-data";
import { cn, entityTypeColor, formatNumber } from "@/lib/utils";
import type { TopicDetail } from "@/types";

type MetricState = "available" | "pending" | "empty";

interface MetricItem {
  label: string;
  value?: string | number | null;
  hint?: string;
  state?: MetricState;
  icon: ReactNode;
}

function formatDateTime(value?: string | null) {
  if (!value) return "n/a";
  return format(parseISO(value), "dd MMM HH:mm");
}

function formatPercent(value?: number | null, signed = false) {
  if (value === undefined || value === null) return null;
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${signed && normalized > 0 ? "+" : ""}${Math.round(normalized)}%`;
}

function formatScore(value?: number | null) {
  if (value === undefined || value === null) return null;
  return value <= 1 ? value.toFixed(2) : Math.round(value).toString();
}

function latestDelta(points: TopicDetail["volume_timeline"]) {
  if (points.length < 2) return null;
  const previous = points[points.length - 2]?.count || 0;
  const current = points[points.length - 1]?.count || 0;
  if (previous === 0) return null;
  return (current - previous) / previous;
}

function statusLabel(detail: TopicDetail) {
  if (detail.status) return detail.status;
  if (detail.is_new) return "new";
  const growth = detail.kpi_metrics?.growth_rate ?? latestDelta(detail.volume_timeline);
  if (growth !== null && growth !== undefined) {
    if (growth > 0.08) return "growing";
    if (growth < -0.08) return "declining";
  }
  return "stable";
}

function MetricTile({ metric, index }: { metric: MetricItem; index: number }) {
  const state = metric.state || (metric.value === undefined || metric.value === null ? "pending" : "available");
  const isAvailable = state === "available";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.035, duration: 0.28 }}
      className={cn(
        "min-h-[108px] border border-border bg-card p-4",
        isAvailable ? "shadow-sm" : "bg-muted/35"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{metric.label}</div>
        <div className={cn("text-primary", !isAvailable && "text-muted-foreground")}>{metric.icon}</div>
      </div>
      <div className="mt-3 text-2xl font-semibold text-foreground">
        {isAvailable ? metric.value : state === "empty" ? "No data" : "Pending"}
      </div>
      {metric.hint && <div className="mt-2 text-xs leading-5 text-muted-foreground">{metric.hint}</div>}
    </motion.div>
  );
}

function SectionShell({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-4", className)}>
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function EmptyAnalyticState({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center border border-dashed border-border bg-muted/25 p-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

export default function TopicDetailPage({ params }: { params: Promise<{ clusterId: string }> }) {
  const { clusterId } = use(params);
  const { data: detail, isLoading } = useTopicDetail(clusterId);

  if (isLoading || !detail) {
    return (
      <>
        <Header title="Topic analytics" />
        <div className="p-6">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-[108px] animate-pulse border border-border bg-muted/50" />
            ))}
          </div>
          <div className="flex items-center justify-center py-24">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        </div>
      </>
    );
  }

  const sourceDisplay = detail.first_source?.display_source;
  const graph = detail.graph_analytics;
  const growth = detail.kpi_metrics?.growth_rate ?? latestDelta(detail.volume_timeline);
  const sourceConfidence =
    detail.source_provenance?.source_confidence ?? sourceDisplay?.source_confidence ?? null;
  const status = statusLabel(detail);
  const summary =
    detail.summary ||
    `${formatNumber(detail.message_count)} messages across ${detail.channel_count} channels since ${formatDateTime(detail.first_seen)}.`;

  const kpiMetrics: MetricItem[] = [
    { label: "Messages", value: formatNumber(detail.message_count), hint: "Cluster volume", icon: <Hash className="h-4 w-4" /> },
    { label: "Channels", value: formatNumber(detail.channel_count), hint: "Distinct publishers", icon: <Radio className="h-4 w-4" /> },
    { label: "Avg sentiment", value: detail.avg_sentiment.toFixed(2), hint: "Mean message score", icon: <Activity className="h-4 w-4" /> },
    {
      label: "Importance",
      value: formatScore(detail.kpi_metrics?.importance_score),
      hint: "Needs backend score",
      icon: <Gauge className="h-4 w-4" />,
    },
    {
      label: "Novelty",
      value: formatScore(detail.kpi_metrics?.novelty_score),
      hint: "Newness against recent topics",
      icon: <CircleDot className="h-4 w-4" />,
    },
    {
      label: "Growth rate",
      value: formatPercent(growth, true),
      hint: detail.kpi_metrics?.growth_rate === undefined ? "Estimated from timeline" : "Backend metric",
      icon: <TrendingUp className="h-4 w-4" />,
    },
    {
      label: "Communities",
      value: graph?.communities_count,
      hint: "Graph analytics",
      icon: <Network className="h-4 w-4" />,
    },
    {
      label: "Graph density",
      value: graph?.density !== undefined && graph?.density !== null ? graph.density.toFixed(3) : null,
      hint: "Edges over possible edges",
      icon: <Share2 className="h-4 w-4" />,
    },
    {
      label: "Bridge nodes",
      value: graph?.bridge_nodes_count,
      hint: "Cross-community connectors",
      icon: <GitBranch className="h-4 w-4" />,
    },
    {
      label: "Source confidence",
      value: formatPercent(sourceConfidence),
      hint: "Exact or inferred provenance",
      icon: <ShieldCheck className="h-4 w-4" />,
    },
  ];

  const graphMetrics: MetricItem[] = [
    { label: "Nodes", value: graph?.node_count, icon: <CircleDot className="h-4 w-4" /> },
    { label: "Edges", value: graph?.edge_count, icon: <Share2 className="h-4 w-4" /> },
    { label: "Communities", value: graph?.communities_count, icon: <Network className="h-4 w-4" /> },
    { label: "Bridge nodes", value: graph?.bridge_nodes_count, icon: <GitBranch className="h-4 w-4" /> },
    {
      label: "Density",
      value: graph?.density !== undefined && graph?.density !== null ? graph.density.toFixed(3) : null,
      icon: <Split className="h-4 w-4" />,
    },
  ];

  return (
    <>
      <Header title={detail.label} />
      <PageTransition>
        <div className="space-y-8 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Link href="/topics" className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
              <ArrowLeft className="h-4 w-4" />
              Back to topics
            </Link>
            <div className="flex items-center gap-2">
              <Link href={`/graph?mode=propagation&clusterId=${encodeURIComponent(clusterId)}`}>
                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  className="flex items-center gap-1.5 rounded-lg bg-muted px-3 py-2 text-sm text-foreground transition-colors hover:bg-accent"
                >
                  <Share2 className="h-4 w-4" />
                  View in graph
                </motion.button>
              </Link>
              <motion.button
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                className="flex items-center gap-1.5 rounded-lg bg-muted px-3 py-2 text-sm text-foreground transition-colors hover:bg-accent"
              >
                <Download className="h-4 w-4" />
                Export
              </motion.button>
            </div>
          </div>

          <section className="border-b border-border pb-6">
            <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-primary/10 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-primary">
                    {status}
                  </span>
                  {detail.is_new && <Badge variant="new">NEW</Badge>}
                  {detail.first_source?.source_status && <SourceStatusBadge status={detail.first_source.source_status} />}
                </div>
                <h1 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">{detail.label}</h1>
                <p className="mt-3 max-w-4xl text-sm leading-6 text-muted-foreground">{summary}</p>
              </div>
              <div className="border-l border-border pl-5 max-xl:border-l-0 max-xl:border-t max-xl:pt-4 max-xl:pl-0">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">First source</div>
                <div className="mt-2 text-lg font-semibold text-foreground">
                  {detail.source_provenance?.first_source_channel || sourceDisplay?.source_channel || "Unknown"}
                </div>
                <div className="mt-1 text-sm text-muted-foreground">
                  First seen {formatDateTime(detail.source_provenance?.first_seen || sourceDisplay?.source_message_date || detail.first_seen)}
                </div>
                <div className="mt-3 flex items-center gap-2 text-sm">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  <span className="font-medium text-foreground">{formatPercent(sourceConfidence) || "Pending"}</span>
                  <span className="text-muted-foreground">source confidence</span>
                </div>
              </div>
            </div>
          </section>

          <SectionShell title="KPI metrics" description="Primary decision metrics for the selected topic. Pending cells are ready for backend fields.">
            <div className="grid overflow-hidden border border-border sm:grid-cols-2 lg:grid-cols-5">
              {kpiMetrics.map((metric, index) => (
                <MetricTile key={metric.label} metric={metric} index={index} />
              ))}
            </div>
          </SectionShell>

          <SectionShell title="Dynamics" description="Volume trend, growth signal and timeline events.">
            <div className="grid gap-6 xl:grid-cols-[1.5fr_0.7fr]">
              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>Message volume</CardTitle>
                </CardHeader>
                {detail.volume_timeline.length > 0 ? (
                  <VolumeLineChart data={detail.volume_timeline} />
                ) : (
                  <EmptyAnalyticState>No volume timeline was returned for this topic.</EmptyAnalyticState>
                )}
              </Card>
              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>Timeline annotations</CardTitle>
                </CardHeader>
                {(detail.timeline_annotations || []).length > 0 ? (
                  <div className="space-y-3">
                    {detail.timeline_annotations!.map((event) => (
                      <div key={`${event.time}-${event.label}`} className="border-l-2 border-primary pl-3">
                        <div className="text-xs text-muted-foreground">{formatDateTime(event.time)}</div>
                        <div className="mt-1 text-sm font-medium text-foreground">{event.label}</div>
                        {event.description && <div className="mt-1 text-sm text-muted-foreground">{event.description}</div>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyAnalyticState>Timeline events are not available yet.</EmptyAnalyticState>
                )}
              </Card>
            </div>
          </SectionShell>

          <SectionShell title="Structure" description="Topic composition by entities, channels, related clusters and sentiment.">
            <div className="grid gap-6 xl:grid-cols-[1fr_1fr_0.8fr]">
              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>High-frequency entities</CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">Frequency ranking, not centrality, unless backend adds centrality metrics.</p>
                </CardHeader>
                <div className="space-y-2">
                  {detail.top_entities.length > 0 ? detail.top_entities.map((entity) => (
                    <Link key={entity.id} href={`/entities/${entity.id}`}>
                      <div className="flex items-center justify-between px-2 py-2 transition-colors hover:bg-accent">
                        <div className="flex min-w-0 items-center gap-2">
                          <Badge variant="entity" color={entityTypeColor(entity.type)}>{entity.type}</Badge>
                          <span className="truncate text-sm text-foreground">{entity.text}</span>
                        </div>
                        <span className="text-xs text-muted-foreground">{formatNumber(entity.mention_count || 0)}</span>
                      </div>
                    </Link>
                  )) : <EmptyAnalyticState>No entities were returned for this topic.</EmptyAnalyticState>}
                </div>
              </Card>

              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>Channel distribution</CardTitle>
                </CardHeader>
                {detail.channels.length > 0 ? (
                  <ChannelBarChart data={detail.channels} />
                ) : (
                  <EmptyAnalyticState>No channel distribution was returned.</EmptyAnalyticState>
                )}
              </Card>

              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>Sentiment mix</CardTitle>
                </CardHeader>
                <SentimentDonutChart breakdown={detail.sentiment_breakdown} />
                <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                  <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-positive" />Positive</span>
                  <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-neutral-sentiment" />Neutral</span>
                  <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-negative" />Negative</span>
                </div>
              </Card>
            </div>

            <Card className="rounded-none">
              <CardHeader>
                <CardTitle>Related topics</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">Similarity is shown as an affinity score to make the list easier to scan.</p>
              </CardHeader>
              {detail.related_topics.length > 0 ? (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {detail.related_topics.map((related) => (
                    <Link key={related.cluster_id} href={`/topics/${related.cluster_id}`}>
                      <motion.div whileHover={{ x: 3 }} className="border border-border p-3 transition-colors hover:bg-accent">
                        <div className="text-sm font-medium text-foreground">{related.label}</div>
                        <div className="mt-2 h-1.5 bg-muted">
                          <div className="h-full bg-primary" style={{ width: `${Math.min(100, Math.round(related.similarity * 100))}%` }} />
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">{Math.round(related.similarity * 100)}% affinity</div>
                      </motion.div>
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyAnalyticState>No related topics were returned.</EmptyAnalyticState>
              )}
            </Card>
          </SectionShell>

          <SectionShell title="Graph analytics" description="Network-level metrics for structure, communities and bridges.">
            {graph ? (
              <div className="space-y-4">
                <div className="grid overflow-hidden border border-border sm:grid-cols-2 lg:grid-cols-5">
                  {graphMetrics.map((metric, index) => (
                    <MetricTile key={metric.label} metric={metric} index={index} />
                  ))}
                </div>
                <div className="grid gap-4 lg:grid-cols-3">
                  <div className="border border-border bg-card p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Top central entity</div>
                    <div className="mt-2 text-sm font-semibold text-foreground">{graph.top_central_entity?.text || "Pending"}</div>
                  </div>
                  <div className="border border-border bg-card p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Top central channel</div>
                    <div className="mt-2 text-sm font-semibold text-foreground">{graph.top_central_channel?.channel || "Pending"}</div>
                  </div>
                  <div className="border border-border bg-card p-4">
                    <div className="text-xs uppercase tracking-wide text-muted-foreground">Graph summary</div>
                    <div className="mt-2 text-sm text-foreground">{graph.summary || "No graph summary returned."}</div>
                  </div>
                </div>
              </div>
            ) : (
              <EmptyAnalyticState>
                Graph analytics were not returned by the API yet. The section is reserved for nodes, edges, communities, bridge nodes, central hubs and density.
              </EmptyAnalyticState>
            )}
          </SectionShell>

          <SectionShell title="Source and provenance" description="Attribution, first seen signal and propagation evidence are treated as analytic inputs.">
            <SourcePanel source={detail.first_source} />
          </SectionShell>

          <SectionShell title="Representative messages">
            <Card className="rounded-none">
              <div className="space-y-3">
                {detail.representative_messages.length > 0 ? detail.representative_messages.map((message, index) => (
                  <MessageCard key={message.event_id} message={message} index={index} />
                )) : <EmptyAnalyticState>No representative messages were returned.</EmptyAnalyticState>}
              </div>
            </Card>
          </SectionShell>
        </div>
      </PageTransition>
    </>
  );
}
