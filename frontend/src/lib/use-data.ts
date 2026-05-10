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
  AnnotationGuidelines,
  AnnotationStats,
  AnnotationTask,
  ClusterId,
  DatasetVersion,
  Entity,
  EntityAlias,
  EntityTimelinePoint,
  FirstSourcePayload,
  GraphData,
  LlmEnrichmentResponse,
  Message,
  ModelVersion,
  OverviewStats,
  SentimentPoint,
  Topic,
  TopicComparisonResult,
  TopicDetail,
  TopicExperiment,
  TopicExperimentMetrics,
  TopicGraphMetricsApiResponse,
  TopicNoveltyPayload,
  TopicReviewTask,
  TopicSimilarityHistoryItem,
  TopicSummaryBundle,
  TopicTimelineApiResponse,
  TrainingJob,
  TrainingTaskType,
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

export function useNovelTopics(minScore = 0.55) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();

  return useErrorReporter(
    useQuery<Topic[]>({
      queryKey: ["novelTopics", from, to, minScore, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockTopics.filter((topic) => topic.is_new))
          : api.getNovelTopics(from, to, minScore),
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

export function useTopicExperiments() {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TopicExperiment[]>({
      queryKey: ["topicExperiments", isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getTopicExperiments()),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useTopicReviewTasks(status = "pending") {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TopicReviewTask[]>({
      queryKey: ["topicReviewTasks", status, isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getTopicReviewTasks(status)),
      refetchInterval: isDemo ? false : 10_000,
    })
  );
}

export function useTopicReviewTask(taskId: string | null) {
  const { isDemo } = useDemoContext();
  return useQuery<TopicReviewTask | null>({
    queryKey: ["topicReviewTask", taskId, isDemo],
    enabled: Boolean(taskId),
    queryFn: () => (!taskId || isDemo ? Promise.resolve(null) : api.getTopicReviewTask(taskId)),
    staleTime: 30_000,
  });
}

export function useTopicExperimentMetrics(experimentId?: string | null) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TopicExperimentMetrics | null>({
      queryKey: ["topicExperimentMetrics", experimentId, isDemo],
      enabled: Boolean(experimentId),
      queryFn: () =>
        !experimentId || isDemo
          ? Promise.resolve(null)
          : api.getTopicExperimentMetrics(experimentId),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
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

export function useTopicSummary(clusterId: ClusterId, language = "ru") {
  const { isDemo } = useDemoContext();
  return useQuery<TopicSummaryBundle | null>({
    queryKey: ["topicSummary", clusterId, language],
    queryFn: () =>
      isDemo ? Promise.resolve(null) : api.getTopicSummary(clusterId, language),
    retry: false,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

export function useTopicNovelty(clusterId: ClusterId) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TopicNoveltyPayload | null>({
      queryKey: ["topicNovelty", clusterId, isDemo],
      queryFn: () =>
        isDemo ? Promise.resolve(mockTopicDetail(clusterId).novelty ?? null) : api.getTopicNovelty(clusterId),
      retry: false,
    })
  );
}

export function useTopicSimilarHistory(clusterId: ClusterId) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TopicSimilarityHistoryItem[]>({
      queryKey: ["topicSimilarHistory", clusterId, isDemo],
      queryFn: () =>
        isDemo
          ? Promise.resolve(mockTopicDetail(clusterId).similar_history ?? [])
          : api.getTopicSimilarHistory(clusterId),
      retry: false,
    })
  );
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

export function useChannels() {
  const { isDemo } = useDemoContext();
  return useQuery<string[]>({
    queryKey: ["channels", isDemo],
    queryFn: async () => {
      if (isDemo) return [];
      const res = await api.getChannels();
      return res.channels;
    },
    staleTime: 5 * 60_000,
  });
}

export function useAnnotationTopics() {
  const { isDemo } = useDemoContext();
  return useQuery<string[]>({
    queryKey: ["annotationTopics", isDemo],
    queryFn: async () => {
      if (isDemo) return [];
      const res = await api.getAnnotationTopics();
      return res.topics;
    },
    staleTime: 60_000,
  });
}

export function useDatasets() {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<DatasetVersion[]>({
      queryKey: ["datasets", isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getDatasets()),
      refetchInterval: isDemo ? false : config.pollingIntervalMs,
    })
  );
}

export function useDataset(datasetId: string | null, taskType: TrainingTaskType = "topic_classification") {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<DatasetVersion | null>({
      queryKey: ["dataset", datasetId, taskType, isDemo],
      enabled: Boolean(datasetId),
      queryFn: () => (!datasetId || isDemo ? Promise.resolve(null) : api.getDataset(datasetId, taskType)),
    })
  );
}

export function useTrainingJobs() {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TrainingJob[]>({
      queryKey: ["trainingJobs", isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getTrainingJobs()),
      refetchInterval: isDemo ? false : 10_000,
    })
  );
}

export function useTrainingJob(jobId: string | null) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<TrainingJob | null>({
      queryKey: ["trainingJob", jobId, isDemo],
      enabled: Boolean(jobId),
      queryFn: () => (!jobId || isDemo ? Promise.resolve(null) : api.getTrainingJob(jobId)),
      refetchInterval: isDemo ? false : 5_000,
    })
  );
}

export function useModels() {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<ModelVersion[]>({
      queryKey: ["models", isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getModels()),
      refetchInterval: isDemo ? false : 10_000,
    })
  );
}

export function useModel(modelId: string | null) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<ModelVersion | null>({
      queryKey: ["model", modelId, isDemo],
      enabled: Boolean(modelId),
      queryFn: () => (!modelId || isDemo ? Promise.resolve(null) : api.getModel(modelId)),
      refetchInterval: isDemo ? false : 10_000,
    })
  );
}

export function useAnnotationTasks(filters?: {
  status?: string;
  dataset_id?: string;
  annotator_id?: string;
  limit?: number;
}) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<AnnotationTask[]>({
      queryKey: ["annotationTasks", filters, isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getAnnotationTasks(filters)),
      refetchInterval: isDemo ? false : 10_000,
    })
  );
}

export function useAnnotationTask(taskId: string | null) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<AnnotationTask | null>({
      queryKey: ["annotationTask", taskId, isDemo],
      enabled: Boolean(taskId),
      queryFn: () => (!taskId || isDemo ? Promise.resolve(null) : api.getAnnotationTask(taskId)),
    })
  );
}

export function useAnnotationStats(datasetId?: string) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<AnnotationStats[]>({
      queryKey: ["annotationStats", datasetId, isDemo],
      queryFn: () => (isDemo ? Promise.resolve([]) : api.getAnnotationStats(datasetId)),
      refetchInterval: isDemo ? false : 30_000,
    })
  );
}

export function useAnnotationGuidelines() {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<AnnotationGuidelines | null>({
      queryKey: ["annotationGuidelines", isDemo],
      queryFn: () => (isDemo ? Promise.resolve(null) : api.getAnnotationGuidelines()),
      staleTime: 5 * 60_000,
    })
  );
}

export function useEntity(id: string | null) {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();
  return useErrorReporter(
    useQuery<Entity | null>({
      queryKey: ["entity", id, from, to, isDemo],
      enabled: Boolean(id),
      queryFn: () => (!id || isDemo ? Promise.resolve(null) : api.getEntityById(id, from, to)),
      staleTime: 30_000,
    })
  );
}

export function useEntityAliases(id: string | null) {
  const { isDemo } = useDemoContext();
  return useErrorReporter(
    useQuery<EntityAlias[]>({
      queryKey: ["entityAliases", id, isDemo],
      enabled: Boolean(id),
      queryFn: () => (!id || isDemo ? Promise.resolve([]) : api.getEntityAliases(id)),
      staleTime: 60_000,
    })
  );
}

export function useEntityMentionTimeline(id: string | null, bucket = "day") {
  const { isDemo } = useDemoContext();
  const { from, to } = useTimeParams();
  return useErrorReporter(
    useQuery<EntityTimelinePoint[]>({
      queryKey: ["entityTimeline", id, from, to, bucket, isDemo],
      enabled: Boolean(id),
      queryFn: () =>
        !id || isDemo ? Promise.resolve([]) : api.getEntityMentionTimeline(id, from, to, bucket),
      staleTime: 30_000,
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
