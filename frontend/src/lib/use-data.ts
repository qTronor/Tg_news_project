"use client";

import { useEffect } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useDemoContext, useGlobalTimeRange } from "@/components/providers";
import { api } from "./api";
import {
  mockOverview,
  mockTopics,
  mockTopicDetail,
  mockEntities,
  mockSentiment,
  mockMessages,
  mockGraph,
} from "./mock-data";
import { config } from "./config";
import type {
  OverviewStats,
  Topic,
  TopicDetail,
  Message,
  Entity,
  SentimentPoint,
  GraphData,
} from "@/types";

function useTimeParams() {
  const { range } = useGlobalTimeRange();
  return range;
}

function useErrorReporter<T>(query: UseQueryResult<T>): UseQueryResult<T> {
  const { setLastError } = useDemoContext();

  useEffect(() => {
    if (query.error) {
      setLastError(
        query.error instanceof Error
          ? query.error.message
          : "Failed to connect to API"
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

export function useTopicDetail(clusterId: number) {
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

export function useEntities(entityType?: string, clusterId?: number) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<Entity[]>({
      queryKey: ["entities", entityType, clusterId, from, to, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(
              mockEntities.filter(
                (e) => !entityType || entityType === "All" || e.type === entityType
              )
            )
          : api.getTopEntities(from, to, entityType, clusterId),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useSentiment(bucket = "hour", channel?: string, clusterId?: number) {
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
  topic?: string;
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
          let msgs = [...mockMessages];
          if (filters?.channel && filters.channel !== "All")
            msgs = msgs.filter((m) => m.channel === filters.channel);
          if (filters?.topic && filters.topic !== "All")
            msgs = msgs.filter((m) => m.topic_label === filters.topic);
          if (filters?.search)
            msgs = msgs.filter((m) =>
              m.text.toLowerCase().includes(filters.search!.toLowerCase())
            );
          if (filters?.sentiment && filters.sentiment !== "All") {
            msgs = msgs.filter((m) => {
              const s = m.sentiment_score || 0;
              if (filters.sentiment === "Positive") return s > 0.2;
              if (filters.sentiment === "Negative") return s < -0.2;
              return s >= -0.2 && s <= 0.2;
            });
          }
          return Promise.resolve(msgs);
        }
        return api.getMessages(from, to, filters);
      },
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useGraph(focusId?: string, depth = 2) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<GraphData>({
      queryKey: ["graph", focusId, depth, from, to, isDemo],
      queryFn: () =>
        isDemo ? Promise.resolve(mockGraph) : api.getGraph(from, to, focusId, depth),
    })
  );
}
