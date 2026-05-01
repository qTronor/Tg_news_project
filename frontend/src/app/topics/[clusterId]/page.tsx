"use client";

import { use, useMemo, useState, type ReactNode } from "react";
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
  RefreshCw,
  Share2,
  ShieldCheck,
  Sparkles,
  Split,
  TrendingUp,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Header } from "@/components/layout/header";
import { PageTransition } from "@/components/layout/page-transition";
import { useGlobalTimeRange } from "@/components/providers";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MessageCard } from "@/components/feed/message-card";
import { SourcePanel } from "@/components/topics/source-panel";
import { SourceStatusBadge } from "@/components/topics/source-status-badge";
import { VolumeLineChart } from "@/components/charts/volume-line";
import { ChannelBarChart } from "@/components/charts/channel-bar";
import { SentimentDonutChart } from "@/components/charts/sentiment-donut";
import { useLlmEnrichment, useTopicComparison, useTopicDetail, useTopicGraphMetrics, useTopicTimeline, useTopics } from "@/lib/use-data";
import { api } from "@/lib/api";
import { cn, entityTypeColor, formatNumber } from "@/lib/utils";
import type {
  ClusterId,
  ClusterExplanationResult,
  ClusterSummaryResult,
  LlmEnrichmentResponse,
  NoveltyExplanationResult,
  Topic,
  TopicComparisonResult,
  TopicDetail,
  TopicGraphAnalytics,
  TopicGraphMetricsApiResponse,
  TopicTimelineAnnotation,
  TopicTimelineApiEvent,
} from "@/types";

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

function formatGraphSummary(graph: TopicGraphMetricsApiResponse) {
  const summary = graph.summary;
  const fragments = [
    `${summary.node_count} nodes`,
    `${summary.edge_count} edges`,
    summary.community_count != null ? `${summary.community_count} communities` : null,
    summary.density != null ? `density ${summary.density.toFixed(3)}` : null,
  ].filter(Boolean);
  return fragments.join(" · ");
}

function normalizeGraphAnalytics(
  detail: TopicDetail,
  graphMetrics?: TopicGraphMetricsApiResponse | null,
): TopicGraphAnalytics | null {
  if (detail.graph_analytics) return detail.graph_analytics;
  if (!graphMetrics?.summary) return null;

  return {
    node_count: graphMetrics.summary.node_count,
    edge_count: graphMetrics.summary.edge_count,
    communities_count: graphMetrics.summary.community_count ?? null,
    bridge_nodes_count: graphMetrics.bridge_nodes?.length ?? null,
    density: graphMetrics.summary.density ?? null,
    top_central_entity: graphMetrics.top_entities?.[0] ?? null,
    top_central_channel: graphMetrics.top_channels?.[0] ?? null,
    summary: formatGraphSummary(graphMetrics),
  };
}

function normalizeTimelineAnnotations(
  detail: TopicDetail,
  timelineEvents?: TopicTimelineApiEvent[] | null,
): TopicTimelineAnnotation[] {
  if ((detail.timeline_annotations || []).length > 0) return detail.timeline_annotations || [];
  return (timelineEvents || []).map((event) => ({
    time: event.event_time,
    label: event.summary,
    description: event.event_type.replaceAll("_", " "),
  }));
}

function deriveNoveltyScore(detail: TopicDetail) {
  const direct = detail.kpi_metrics?.novelty_score;
  if (direct !== undefined && direct !== null) return direct;
  const components = detail.score_breakdown?.components as Record<string, { normalized?: number; raw?: number }> | undefined;
  const novelty = components?.novelty;
  if (novelty?.normalized !== undefined) return novelty.normalized;
  if (novelty?.raw !== undefined) return novelty.raw;
  return null;
}

function formatShortPercent(value?: number | null) {
  if (value === undefined || value === null) return "n/a";
  return `${Math.round(value * 100)}%`;
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

const LEVEL_COLORS: Record<string, string> = {
  low: "text-muted-foreground bg-muted",
  medium: "text-primary bg-primary/10",
  high: "text-amber-600 bg-amber-500/15 dark:text-amber-400",
  critical: "text-destructive bg-destructive/15",
};

const COMPONENT_LABELS: Record<string, string> = {
  growth_rate: "Growth rate",
  message_count: "Volume",
  unique_channels: "Channel reach",
  new_channel_ratio: "New channels",
  unique_entities: "Entity richness",
  novelty: "Entity novelty",
  sentiment_intensity: "Sentiment intensity",
  sentiment_shift: "Sentiment shift",
  cluster_density: "Graph density",
};

const COMPARISON_LABELS: Record<string, string> = {
  embedding: "Embedding",
  entities: "Entities",
  channels: "Channels",
  time: "Time",
  messages: "Messages",
  sentiment: "Sentiment",
};

const COMPARISON_CLASS_STYLES: Record<string, string> = {
  same_topic: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  related_topics: "bg-primary/10 text-primary",
  possible_subtopic_split: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  different_topics: "bg-muted text-muted-foreground",
};

interface ComponentScore {
  raw: number;
  normalized: number;
  weight: number;
  contribution: number;
}

function ImportanceBreakdownPanel({
  breakdown,
  level,
  score,
}: {
  breakdown: Record<string, unknown>;
  level?: string | null;
  score?: number | null;
}) {
  const components = breakdown.components as Record<string, ComponentScore> | undefined;
  if (!components) return null;

  const sorted = Object.entries(components).sort(
    ([, a], [, b]) => (b as ComponentScore).contribution - (a as ComponentScore).contribution
  );

  const maxContrib = Math.max(...sorted.map(([, c]) => (c as ComponentScore).contribution));

  return (
    <div className="border border-border bg-card p-5 space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-2xl font-semibold text-foreground">{score != null ? score.toFixed(2) : "—"}</span>
        {level && (
          <span className={cn("rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide", LEVEL_COLORS[level] ?? "bg-muted text-muted-foreground")}>
            {level}
          </span>
        )}
      </div>
      <div className="space-y-2">
        {sorted.map(([key, c]) => {
          const comp = c as ComponentScore;
          const barPct = maxContrib > 0 ? (comp.contribution / maxContrib) * 100 : 0;
          return (
            <div key={key} className="grid grid-cols-[160px_1fr_56px] items-center gap-3">
              <span className="text-xs text-muted-foreground truncate">{COMPONENT_LABELS[key] ?? key}</span>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${barPct}%` }} />
              </div>
              <span className="text-xs font-medium text-foreground text-right">{(comp.contribution * 100).toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
      {(breakdown.penalties as unknown[])?.length > 0 && (
        <p className="text-xs text-muted-foreground border-t border-border pt-3">
          Small-cluster penalty applied (×{(breakdown.penalty_factor as number).toFixed(2)})
        </p>
      )}
    </div>
  );
}

function TopicComparisonPanel({
  currentTopic,
  topics,
  selectedClusterId,
  onSelectCluster,
  comparison,
  isLoading,
}: {
  currentTopic: TopicDetail;
  topics: Topic[];
  selectedClusterId: ClusterId | null;
  onSelectCluster: (clusterId: ClusterId | null) => void;
  comparison?: TopicComparisonResult | null;
  isLoading: boolean;
}) {
  const candidates = topics.filter((topic) => topic.cluster_id !== currentTopic.cluster_id);
  const sortedBreakdown = comparison
    ? Object.entries(comparison.breakdown).sort(([, a], [, b]) => b.contribution - a.contribution)
    : [];
  const maxContribution = Math.max(0.001, ...sortedBreakdown.map(([, item]) => item.contribution));

  return (
    <Card className="rounded-none">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Compare topics</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Deterministic comparison over entities, channels, time, representative messages and sentiment.
            </p>
          </div>
          <select
            value={selectedClusterId ?? ""}
            onChange={(event) => onSelectCluster(event.target.value || null)}
            className="h-9 min-w-[240px] border border-border bg-background px-3 text-sm text-foreground outline-none transition-colors hover:bg-accent focus:border-primary"
          >
            <option value="">Select topic</option>
            {candidates.map((topic) => (
              <option key={topic.cluster_id} value={topic.cluster_id}>
                {topic.label}
              </option>
            ))}
          </select>
        </div>
      </CardHeader>

      {!selectedClusterId ? (
        <EmptyAnalyticState>Select a second topic to calculate an explainable comparison.</EmptyAnalyticState>
      ) : isLoading ? (
        <div className="flex min-h-[220px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
        </div>
      ) : comparison ? (
        <div className="space-y-5">
          <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
            <div className="border border-border bg-muted/20 p-4">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Similarity</div>
              <div className="mt-3 text-4xl font-semibold text-foreground">
                {formatShortPercent(comparison.similarity_score)}
              </div>
              <div
                className={cn(
                  "mt-3 inline-flex rounded px-2 py-1 text-xs font-semibold uppercase tracking-wide",
                  COMPARISON_CLASS_STYLES[comparison.classification] ?? "bg-muted text-muted-foreground"
                )}
              >
                {comparison.classification.replaceAll("_", " ")}
              </div>
              <div className="mt-3 text-xs leading-5 text-muted-foreground">
                {comparison.explanation.summary}
              </div>
            </div>

            <div className="space-y-2">
              {sortedBreakdown.map(([key, item]) => (
                <div key={key} className="grid grid-cols-[112px_1fr_60px] items-center gap-3">
                  <div className="truncate text-xs text-muted-foreground">
                    {COMPARISON_LABELS[key] ?? key}
                  </div>
                  <div className="h-2 overflow-hidden bg-muted">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${Math.round((item.contribution / maxContribution) * 100)}%` }}
                    />
                  </div>
                  <div className="text-right text-xs font-medium text-foreground">
                    {formatShortPercent(item.score)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <div className="border border-border p-4">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Shared entities</div>
              <div className="mt-3 space-y-2">
                {comparison.evidence.entities.shared.length > 0 ? (
                  comparison.evidence.entities.shared.slice(0, 5).map((entity) => (
                    <div key={entity.id} className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate text-foreground">{entity.text}</span>
                      <span className="text-xs text-muted-foreground">
                        {entity.a_mentions}/{entity.b_mentions}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">No shared entities in top evidence.</div>
                )}
              </div>
            </div>

            <div className="border border-border p-4">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Shared channels</div>
              <div className="mt-3 space-y-2">
                {comparison.evidence.channels.shared.length > 0 ? (
                  comparison.evidence.channels.shared.slice(0, 5).map((channel) => (
                    <div key={channel.channel} className="flex items-center justify-between gap-3 text-sm">
                      <span className="truncate text-foreground">{channel.channel}</span>
                      <span className="text-xs text-muted-foreground">
                        {channel.a_count}/{channel.b_count}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-muted-foreground">No shared channels in top evidence.</div>
                )}
              </div>
            </div>

            <div className="border border-border p-4">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Divergence</div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-muted-foreground">Time overlap</div>
                  <div className="mt-1 font-medium text-foreground">
                    {formatShortPercent(comparison.evidence.time.overlap_coefficient)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Sentiment delta</div>
                  <div className="mt-1 font-medium text-foreground">
                    {comparison.evidence.sentiment.delta.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Messages</div>
                  <div className="mt-1 font-medium text-foreground">
                    {formatShortPercent(comparison.evidence.messages.score)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Embedding</div>
                  <div className="mt-1 font-medium text-foreground">
                    {comparison.evidence.embedding.available
                      ? formatShortPercent(comparison.evidence.embedding.score)
                      : "n/a"}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <ComparisonFactorList title="Why close" items={comparison.explanation.positive_factors} />
            <ComparisonFactorList title="Why different" items={comparison.explanation.negative_factors} />
            <ComparisonFactorList title="Split signals" items={comparison.explanation.subtopic_split_signals} />
          </div>
        </div>
      ) : (
        <EmptyAnalyticState>Comparison data is not available for the selected topic pair.</EmptyAnalyticState>
      )}
    </Card>
  );
}

function ComparisonFactorList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="border border-border p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      {items.length > 0 ? (
        <ul className="mt-3 space-y-2 text-sm leading-5 text-foreground">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <div className="mt-3 text-sm text-muted-foreground">No signal.</div>
      )}
    </div>
  );
}

const NOVELTY_LABELS: Record<string, string> = {
  new: "New topic",
  ongoing: "Ongoing",
  resurgent: "Resurgent",
};

const NOVELTY_COLORS: Record<string, string> = {
  new: "text-emerald-700 bg-emerald-500/15 dark:text-emerald-300",
  ongoing: "text-primary bg-primary/10",
  resurgent: "text-amber-600 bg-amber-500/15 dark:text-amber-400",
};

function LlmBlock({
  title,
  response,
  children,
}: {
  title: string;
  response: LlmEnrichmentResponse | undefined;
  children: (result: Record<string, unknown>) => ReactNode;
}) {
  if (!response) {
    return (
      <div className="flex min-h-[80px] items-center justify-center border border-border bg-muted/25 text-xs text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (response.status === "pending") {
    return (
      <div className="flex min-h-[80px] items-center justify-center border border-border bg-muted/25 text-xs text-muted-foreground">
        Computing in background — click Refresh above to generate now.
      </div>
    );
  }
  if (response.status === "error" || response.status === "budget_exhausted") {
    const msg = response.status === "budget_exhausted"
      ? "Daily LLM budget reached. Try again tomorrow."
      : "Generation failed. Click Refresh to retry.";
    return (
      <div className="flex min-h-[80px] items-center justify-center border border-dashed border-destructive/50 bg-destructive/5 text-xs text-muted-foreground">
        {msg}
      </div>
    );
  }
  if (!response.result) {
    return (
      <div className="flex min-h-[80px] items-center justify-center border border-dashed border-border bg-muted/15 text-xs text-muted-foreground">
        No insight payload was returned.
      </div>
    );
  }
  return (
    <div className="border border-border bg-card p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      {children(response.result)}
    </div>
  );
}

function AiInsightsSection({ clusterId }: { clusterId: string }) {
  const queryClient = useQueryClient();
  const [isRefreshing, setIsRefreshing] = useState(false);

  const summaryQuery = useLlmEnrichment(clusterId, "cluster_summary");
  const explanationQuery = useLlmEnrichment(clusterId, "cluster_explanation");
  const noveltyQuery = useLlmEnrichment(clusterId, "novelty_explanation");

  const anyOk = [summaryQuery, explanationQuery, noveltyQuery].some(
    (q) => q.data?.status === "ok"
  );
  const metaSource = [summaryQuery, explanationQuery, noveltyQuery].find(
    (q) => q.data?.status === "ok"
  )?.data;

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      const [s, e, n] = await Promise.allSettled([
        api.refreshLlmEnrichment(clusterId, "cluster_summary"),
        api.refreshLlmEnrichment(clusterId, "cluster_explanation"),
        api.refreshLlmEnrichment(clusterId, "novelty_explanation"),
      ]);
      if (s.status === "fulfilled") {
        queryClient.setQueryData(["llmEnrichment", clusterId, "cluster_summary"], s.value);
      }
      if (e.status === "fulfilled") {
        queryClient.setQueryData(["llmEnrichment", clusterId, "cluster_explanation"], e.value);
      }
      if (n.status === "fulfilled") {
        queryClient.setQueryData(["llmEnrichment", clusterId, "novelty_explanation"], n.value);
      }
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <SectionShell
      title="AI Insights"
      description="Natural-language analysis generated by Mistral. Not a substitute for primary analytics."
    >
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3 border border-border bg-muted/20 px-4 py-2.5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {anyOk && metaSource ? (
              <span>
                {metaSource.model?.name ?? "Mistral"} · {metaSource.language ?? "?"}{" "}
                ({metaSource.analysis_mode ?? "?"})
                {metaSource.cached && (
                  <span className="ml-2 text-primary">· cached</span>
                )}
              </span>
            ) : (
              <span>Mistral · not yet generated</span>
            )}
          </div>
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 rounded border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:opacity-50"
          >
            {isRefreshing ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {isRefreshing ? "Generating…" : "Refresh"}
          </button>
        </div>

        <LlmBlock title="Summary" response={summaryQuery.data}>
          {(result) => {
            const r = result as unknown as ClusterSummaryResult;
            return (
              <div className="space-y-3">
                <p className="text-sm leading-6 text-foreground">{r.summary}</p>
                {r.key_points?.length > 0 && (
                  <ul className="space-y-1">
                    {r.key_points.map((point, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                        <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                        {point}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          }}
        </LlmBlock>

        <div className="grid gap-4 lg:grid-cols-2">
          <LlmBlock title="Why important" response={explanationQuery.data}>
            {(result) => {
              const r = result as unknown as ClusterExplanationResult;
              const maxWeight = Math.max(0.001, ...r.drivers.map((d) => d.weight));
              return (
                <div className="space-y-4">
                  <p className="text-sm leading-6 text-foreground">{r.why_important}</p>
                  {r.drivers?.length > 0 && (
                    <div className="space-y-2">
                      {r.drivers.map((driver, i) => (
                        <div key={i} className="space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-foreground truncate">{driver.name}</span>
                            <span className="text-xs text-muted-foreground shrink-0">{(driver.weight * 100).toFixed(0)}%</span>
                          </div>
                          <div className="h-1 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full"
                              style={{ width: `${(driver.weight / maxWeight) * 100}%` }}
                            />
                          </div>
                          <p className="text-xs text-muted-foreground leading-4">{driver.explanation}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            }}
          </LlmBlock>

          <LlmBlock title="Novelty verdict" response={noveltyQuery.data}>
            {(result) => {
              const r = result as unknown as NoveltyExplanationResult;
              return (
                <div className="space-y-3">
                  <span
                    className={cn(
                      "inline-flex rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide",
                      NOVELTY_COLORS[r.novelty_verdict] ?? "bg-muted text-muted-foreground"
                    )}
                  >
                    {NOVELTY_LABELS[r.novelty_verdict] ?? r.novelty_verdict}
                  </span>
                  <p className="text-sm leading-6 text-foreground">{r.rationale}</p>
                </div>
              );
            }}
          </LlmBlock>
        </div>
      </div>
    </SectionShell>
  );
}

export default function TopicDetailPage({ params }: { params: Promise<{ clusterId: string }> }) {
  const { clusterId } = use(params);
  const [compareClusterId, setCompareClusterId] = useState<ClusterId | null>(null);
  const { preset } = useGlobalTimeRange();
  const { data: detail, isLoading } = useTopicDetail(clusterId);
  const { data: topics = [] } = useTopics();
  const timelineBucket = preset === "7d" || preset === "30d" ? "day" : "hour";
  const timelineQuery = useTopicTimeline(clusterId, timelineBucket);
  const graphMetricsQuery = useTopicGraphMetrics(clusterId);
  const comparisonQuery = useTopicComparison(clusterId, compareClusterId);
  const comparisonTopics = useMemo(() => {
    if (!detail) return topics.filter((topic) => topic.cluster_id !== clusterId);
    const relatedIds = new Set(detail.related_topics.map((topic) => topic.cluster_id));
    return [...topics].sort((left, right) => {
      const leftRelated = relatedIds.has(left.cluster_id) ? 1 : 0;
      const rightRelated = relatedIds.has(right.cluster_id) ? 1 : 0;
      return rightRelated - leftRelated || right.message_count - left.message_count;
    });
  }, [clusterId, detail, topics]);

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
  const graph = normalizeGraphAnalytics(detail, graphMetricsQuery.data);
  const timelineAnnotations = normalizeTimelineAnnotations(detail, timelineQuery.data?.events);
  const noveltyScore = deriveNoveltyScore(detail);
  const volumeTimeline = detail.volume_timeline.length > 0
    ? detail.volume_timeline
    : (timelineQuery.data?.points || []).map((point) => ({
        time: point.bucket_start,
        count: point.message_count,
      }));
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
      value: detail.importance_score != null ? `${detail.importance_score.toFixed(2)} (${detail.importance_level})` : formatScore(detail.kpi_metrics?.importance_score),
      hint: detail.importance_level ? `Level: ${detail.importance_level}` : "Awaiting scoring run",
      state: detail.importance_score != null ? "available" : "pending",
      icon: <Gauge className="h-4 w-4" />,
    },
    {
      label: "Novelty",
      value: formatScore(noveltyScore),
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
                {volumeTimeline.length > 0 ? (
                  <VolumeLineChart data={volumeTimeline} />
                ) : (
                  <EmptyAnalyticState>No volume timeline was returned for this topic.</EmptyAnalyticState>
                )}
              </Card>
              <Card className="rounded-none">
                <CardHeader>
                  <CardTitle>Timeline annotations</CardTitle>
                </CardHeader>
                {timelineAnnotations.length > 0 ? (
                  <div className="space-y-3">
                    {timelineAnnotations.map((event) => (
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

            <TopicComparisonPanel
              currentTopic={detail}
              topics={comparisonTopics}
              selectedClusterId={compareClusterId}
              onSelectCluster={setCompareClusterId}
              comparison={comparisonQuery.data}
              isLoading={comparisonQuery.isFetching}
            />
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

          {detail.score_breakdown && (
            <SectionShell title="Importance breakdown" description="Why this topic was scored the way it was. Each component contributes to the final importance score.">
              <ImportanceBreakdownPanel breakdown={detail.score_breakdown} level={detail.importance_level} score={detail.importance_score} />
            </SectionShell>
          )}

          <AiInsightsSection clusterId={clusterId} />

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
