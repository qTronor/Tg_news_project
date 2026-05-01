"use client";

import { useEffect } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useDemoContext, useGlobalTimeRange } from "@/components/providers";
import { api } from "./api";
import {
  mockEntities,
  mockGraph,
  mockMessages,
  mockOverview,
  mockSentiment,
  mockTopicComparison,
  mockTopicDetail,
  mockTopics,
} from "./mock-data";
import { config } from "./config";
import type {
  ClusterId,
  Entity,
  FirstSourcePayload,
  GraphData,
  LlmEnrichmentResponse,
  Message,
  OverviewStats,
  SentimentPoint,
  Topic,
  TopicComparisonResult,
  TopicDetail,
  TopicGraphMetricsApiResponse,
  TopicTimelineApiResponse,
} from "@/types";

export type GraphMode = "overview" | "propagation";

function useTimeParams() {
  const { range } = useGlobalTimeRange();
  return range;
}

function useErrorReporter<T>(query: UseQueryResult<T>): UseQueryResult<T> {
  const { setLastError } = useDemoContext();

  useEffect(() => {
    if (query.error) {
      setLastError(
        query.error instanceof Error ? query.error.message : "Failed to connect to API"
      );
    }
    if (query.isSuccess) {
      setLastError(null);
    }
  }, [query.error, query.isSuccess, setLastError]);

  return query;
}

export function useOverview() {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<OverviewStats>({
      queryKey: ["overview", from, to, isDemo],
      queryFn: () => (isDemo ? Promise.resolve(mockOverview) : api.getOverview(from, to)),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useTopics() {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<Topic[]>({
      queryKey: ["topics", from, to, isDemo],
      queryFn: () => (isDemo ? Promise.resolve(mockTopics) : api.getClusters(from, to)),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useTopicDetail(clusterId: ClusterId) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<TopicDetail>({
      queryKey: ["topicDetail", clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockTopicDetail(clusterId))
          : api.getClusterDetail(clusterId, from, to),
    })
  );
}

export function useTopicComparison(clusterId: ClusterId, otherClusterId?: ClusterId | null) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<TopicComparisonResult | null>({
      queryKey: ["topicComparison", clusterId, otherClusterId, from, to, isDemo],
      enabled: Boolean(otherClusterId),
      queryFn: () => {
        if (!otherClusterId) return Promise.resolve(null);
        return isDemo
          ? Promise.resolve(mockTopicComparison(clusterId, otherClusterId, from, to))
          : api.getTopicComparison(clusterId, otherClusterId, from, to);
      },
    })
  );
}

export function useClusterFirstSource(clusterId: ClusterId) {
  const { isDemo } = useDemoContext();

  return useErrorReporter(
    useQuery<FirstSourcePayload | null>({
      queryKey: ["clusterFirstSource", clusterId, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockTopicDetail(clusterId).first_source ?? null)
          : api.getClusterFirstSource(clusterId),
    })
  );
}

export function useEntities(entityType?: string, clusterId?: ClusterId) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<Entity[]>({
      queryKey: ["entities", entityType, clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(
              mockEntities.filter(
                (entity) => !entityType || entityType === "All" || entity.type === entityType
              )
            )
          : api.getTopEntities(from, to, entityType, clusterId),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useSentiment(bucket = "hour", channel?: string, clusterId?: ClusterId) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<SentimentPoint[]>({
      queryKey: ["sentiment", bucket, channel, clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockSentiment)
          : api.getSentimentDynamics(from, to, bucket, channel, clusterId),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useMessages(filters?: {
  channel?: string;
  topic?: ClusterId;
  sentiment?: string;
  entity?: string;
  search?: string;
}) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<Message[]>({
      queryKey: ["messages", filters, from, to, isDemo],
      queryFn: () => {
        if (isDemo) {
          let messages = [...mockMessages];
          if (filters?.channel && filters.channel !== "All") {
            messages = messages.filter((message) => message.channel === filters.channel);
          }
          if (filters?.topic && filters.topic !== "All") {
            messages = messages.filter((message) => message.cluster_id === filters.topic);
          }
          if (filters?.search) {
            messages = messages.filter((message) =>
              message.text.toLowerCase().includes(filters.search!.toLowerCase())
            );
          }
          if (filters?.sentiment && filters.sentiment !== "All") {
            messages = messages.filter((message) => {
              const score = message.sentiment_score || 0;
              if (filters.sentiment === "Positive") return score > 0.2;
              if (filters.sentiment === "Negative") return score < -0.2;
              return score >= -0.2 && score <= 0.2;
            });
          }
          return Promise.resolve(messages);
        }
        return api.getMessages(from, to, filters);
      },
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useLlmEnrichment(clusterId: ClusterId, enrichmentType: string) {
  const { isDemo } = useDemoContext();
  return useQuery<LlmEnrichmentResponse>({
    queryKey: ["llmEnrichment", clusterId, enrichmentType],
    queryFn: () =>
      isDemo
        ? Promise.resolve<LlmEnrichmentResponse>({ status: "pending", result: null, is_llm_generated: true })
        : api.getLlmEnrichment(clusterId, enrichmentType),
    retry: false,
    staleTime: 60_000,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 5_000 : false),
  });
}

export function useTopicTimeline(clusterId: ClusterId, bucket = "hour") {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<TopicTimelineApiResponse | null>({
      queryKey: ["topicTimeline", clusterId, bucket, from, to, isDemo],
      queryFn: () =>
        isDemo ? Promise.resolve(null) : api.getClusterTimeline(clusterId, from, to, bucket),
    })
  );
}

export function useTopicGraphMetrics(clusterId: ClusterId) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<TopicGraphMetricsApiResponse | null>({
      queryKey: ["topicGraphMetrics", clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo ? Promise.resolve(null) : api.getClusterGraphMetrics(clusterId, from, to),
    })
  );
}

export function useGraph(
  focusId?: string,
  depth = 2,
  mode: GraphMode = "overview",
  clusterId?: ClusterId
) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<GraphData>({
      queryKey: ["graph", focusId, depth, mode, clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockGraph)
          : api.getGraph(from, to, focusId, depth, mode, clusterId),
    })
  );
}
