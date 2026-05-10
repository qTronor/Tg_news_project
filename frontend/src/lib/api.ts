import { config } from "./config";
import type {
  AnnotationGuidelines,
  AnnotationStats,
  AnnotationTask,
  ClusterId,
  DatasetBuildRequest,
  DatasetVersion,
  Entity,
  EntityAlias,
  EntityTimelinePoint,
  FirstSourcePayload,
  GraphData,
  LabelSubmitRequest,
  LlmEnrichmentResponse,
  MergeResult,
  Message,
  ModelVersion,
  NormalizationRule,
  NormalizationRuleInput,
  OverviewStats,
  SentimentPoint,
  Topic,
  TopicComparisonResult,
  TopicDetail,
  TopicExperiment,
  TopicExperimentMetrics,
  TopicExperimentRunRequest,
  TopicExperimentRunResponse,
  TopicGraphMetricsApiResponse,
  TopicNoveltyPayload,
  TopicReviewActionRequest,
  TopicReviewTask,
  TopicSimilarityHistoryItem,
  TopicSummaryBundle,
  TopicTimelineApiResponse,
  TrainingJob,
  TrainingJobLog,
  TrainingPlan,
  TrainingTaskType,
  DatasetValidationReport,
  ScientificPaper,
  PaperDetail,
  PaperSummary,
} from "@/types";

const BASE = config.apiBaseUrl;
const TIMEOUT_MS = 5_000;
const LLM_REFRESH_TIMEOUT_MS = 35_000;

async function fetchJson<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, BASE);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value) {
        url.searchParams.set(key, value);
      }
    });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(url.toString(), { signal: controller.signal });
    if (!res.ok) {
      throw new Error(`API ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        `API timeout: ${url.pathname} did not respond within ${TIMEOUT_MS / 1000}s`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function postJson<T>(path: string, body?: unknown, timeoutMs = TIMEOUT_MS): Promise<T> {
  const url = new URL(path, BASE);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    if (!res.ok) {
      let msg = `API ${res.status}: ${res.statusText}`;
      try { const j = await res.json(); if (j?.error) msg = j.error; } catch { /* ignore */ }
      throw new Error(msg);
    }
    return await res.json();
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`API timeout: ${url.pathname}`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  getOverview(from: string, to: string): Promise<OverviewStats> {
    return fetchJson("/analytics/overview", { from, to });
  },

  getClusters(from: string, to: string, channel?: string): Promise<Topic[]> {
    return fetchJson("/analytics/topics", {
      from,
      to,
      ...(channel ? { channel } : {}),
    });
  },

  getNovelTopics(from: string, to: string, minScore = 0.55): Promise<Topic[]> {
    return fetchJson("/analytics/topics/novel", {
      from,
      to,
      min_score: String(minScore),
    });
  },

  getClusterDetail(clusterId: ClusterId, from: string, to: string): Promise<TopicDetail> {
    return fetchJson(`/analytics/topics/${encodeURIComponent(clusterId)}`, { from, to });
  },

  getClusterTimeline(
    clusterId: ClusterId,
    from: string,
    to: string,
    bucket = "hour"
  ): Promise<TopicTimelineApiResponse> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/timeline`, {
      from,
      to,
      bucket,
    });
  },

  getClusterGraphMetrics(
    clusterId: ClusterId,
    from: string,
    to: string
  ): Promise<TopicGraphMetricsApiResponse> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/graph-metrics`, {
      from,
      to,
    });
  },

  getClusterDocuments(
    clusterId: ClusterId,
    from: string,
    to: string,
    limit = 50,
    offset = 0
  ): Promise<Message[]> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/documents`, {
      from,
      to,
      limit: String(limit),
      offset: String(offset),
    });
  },

  getClusterFirstSource(clusterId: ClusterId): Promise<FirstSourcePayload> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/first-source`);
  },

  getRelatedClusters(
    clusterId: ClusterId,
    from: string,
    to: string
  ): Promise<{ cluster_id: ClusterId; label: string; similarity: number }[]> {
    return fetchJson(`/analytics/topics/${encodeURIComponent(clusterId)}/similar`, {
      from,
      to,
    });
  },

  getTopicNovelty(clusterId: ClusterId): Promise<TopicNoveltyPayload> {
    return fetchJson(`/analytics/topics/${encodeURIComponent(clusterId)}/novelty`);
  },

  getTopicSimilarHistory(
    clusterId: ClusterId,
    limit = 10
  ): Promise<TopicSimilarityHistoryItem[]> {
    return fetchJson(`/analytics/topics/${encodeURIComponent(clusterId)}/similar-history`, {
      limit: String(limit),
    });
  },

  getTopicComparison(
    clusterId: ClusterId,
    otherClusterId: ClusterId,
    from: string,
    to: string
  ): Promise<TopicComparisonResult> {
    return fetchJson(
      `/analytics/clusters/${encodeURIComponent(clusterId)}/compare/${encodeURIComponent(otherClusterId)}`,
      { from, to }
    );
  },

  getTopicExperiments(): Promise<TopicExperiment[]> {
    return fetchJson("/analytics/experiments/topics");
  },

  getTopicExperimentMetrics(experimentId: string): Promise<TopicExperimentMetrics> {
    return fetchJson(`/analytics/experiments/topics/${encodeURIComponent(experimentId)}/metrics`);
  },

  runTopicExperiment(payload: TopicExperimentRunRequest): Promise<TopicExperimentRunResponse> {
    return postJson("/analytics/experiments/topics/run", payload, 10_000);
  },

  getTopicReviewTasks(status = "pending"): Promise<TopicReviewTask[]> {
    return fetchJson("/analytics/review/topics", { status });
  },

  getTopicReviewTask(taskId: string): Promise<TopicReviewTask> {
    return fetchJson(`/analytics/review/topics/${encodeURIComponent(taskId)}`);
  },

  requestTopicReview(payload: TopicReviewActionRequest & { cluster_id: string }): Promise<{ ok: boolean; task_id: string }> {
    return postJson("/analytics/review/topics", payload);
  },

  confirmTopicReview(taskId: string, payload: TopicReviewActionRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/review/topics/${encodeURIComponent(taskId)}/confirm`, payload);
  },

  renameTopicReview(taskId: string, payload: TopicReviewActionRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/review/topics/${encodeURIComponent(taskId)}/rename`, payload);
  },

  mergeTopicReview(taskId: string, payload: TopicReviewActionRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/review/topics/${encodeURIComponent(taskId)}/merge`, payload);
  },

  splitTopicReview(taskId: string, payload: TopicReviewActionRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/review/topics/${encodeURIComponent(taskId)}/split`, payload);
  },

  rejectTopicReview(taskId: string, payload: TopicReviewActionRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/review/topics/${encodeURIComponent(taskId)}/reject`, payload);
  },

  getTopEntities(
    from: string,
    to: string,
    entityType?: string,
    clusterId?: ClusterId
  ): Promise<Entity[]> {
    return fetchJson("/analytics/entities/top", {
      from,
      to,
      ...(entityType ? { entity_type: entityType } : {}),
      ...(clusterId ? { cluster_id: clusterId } : {}),
    });
  },

  getSentimentDynamics(
    from: string,
    to: string,
    bucket = "hour",
    channel?: string,
    clusterId?: ClusterId
  ): Promise<SentimentPoint[]> {
    return fetchJson("/analytics/sentiment/dynamics", {
      from,
      to,
      bucket,
      ...(channel ? { channel } : {}),
      ...(clusterId ? { cluster_id: clusterId } : {}),
    });
  },

  getGraph(
    from: string,
    to: string,
    focusId?: string,
    depth = 2,
    mode: "overview" | "propagation" = "overview",
    clusterId?: ClusterId
  ): Promise<GraphData> {
    return fetchJson("/analytics/graph", {
      from,
      to,
      depth: String(depth),
      mode,
      ...(focusId ? { focus: focusId } : {}),
      ...(clusterId ? { cluster_id: clusterId } : {}),
    });
  },

  getLlmEnrichment(clusterId: ClusterId, enrichmentType: string): Promise<LlmEnrichmentResponse> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/llm/${enrichmentType}`);
  },

  refreshLlmEnrichment(clusterId: ClusterId, enrichmentType: string): Promise<LlmEnrichmentResponse> {
    return postJson(
      `/analytics/clusters/${encodeURIComponent(clusterId)}/llm/${enrichmentType}/refresh`,
      {},
      LLM_REFRESH_TIMEOUT_MS,
    );
  },

  getTopicSummary(clusterId: ClusterId, language = "ru"): Promise<TopicSummaryBundle> {
    return fetchJson(`/analytics/topics/${encodeURIComponent(clusterId)}/summary`, { language });
  },

  regenerateTopicSummary(clusterId: ClusterId, language = "ru"): Promise<TopicSummaryBundle> {
    return postJson(
      `/analytics/topics/${encodeURIComponent(clusterId)}/summary/regenerate`,
      { language },
      LLM_REFRESH_TIMEOUT_MS,
    );
  },

  // ── Annotation / Dataset API ─────────────────────────────────────────────

  getDatasets(limit = 50): Promise<DatasetVersion[]> {
    return fetchJson("/analytics/datasets", { limit: String(limit) });
  },

  getDataset(datasetId: string, taskType: TrainingTaskType = "topic_classification"): Promise<DatasetVersion> {
    return fetchJson(`/analytics/datasets/${encodeURIComponent(datasetId)}`, { task_type: taskType });
  },

  getDatasetValidation(datasetId: string, taskType: TrainingTaskType): Promise<DatasetValidationReport> {
    return fetchJson(`/analytics/datasets/${encodeURIComponent(datasetId)}/validation`, {
      task_type: taskType,
    });
  },

  validateDataset(datasetId: string, taskType: TrainingTaskType): Promise<DatasetValidationReport> {
    return postJson(`/analytics/datasets/${encodeURIComponent(datasetId)}/validate`, {
      task_type: taskType,
    });
  },

  buildDataset(payload: DatasetBuildRequest): Promise<{ id: string; status: string }> {
    return postJson("/analytics/datasets/build", payload, 120_000);
  },

  getDatasetExportUrl(datasetId: string, format: string): string {
    return `${BASE}/analytics/datasets/${encodeURIComponent(datasetId)}/export?format=${format}`;
  },

  previewTraining(payload: {
    dataset_id: string;
    task_type: TrainingTaskType;
    base_model?: string;
    training_config?: Record<string, unknown>;
  }): Promise<TrainingPlan> {
    return postJson("/analytics/training/jobs/preview", payload);
  },

  createTrainingJob(payload: {
    dataset_id: string;
    task_type: TrainingTaskType;
    base_model: string;
    training_config?: Record<string, unknown>;
    consent_to_train: boolean;
    actor_user_id?: string;
  }): Promise<TrainingJob> {
    return postJson("/analytics/training/jobs", payload, 15_000);
  },

  getTrainingJobs(): Promise<TrainingJob[]> {
    return fetchJson("/analytics/training/jobs");
  },

  getTrainingJob(jobId: string): Promise<TrainingJob> {
    return fetchJson(`/analytics/training/jobs/${encodeURIComponent(jobId)}`);
  },

  cancelTrainingJob(jobId: string): Promise<TrainingJob> {
    return postJson(`/analytics/training/jobs/${encodeURIComponent(jobId)}/cancel`, {});
  },

  getTrainingJobLogs(jobId: string): Promise<TrainingJobLog[]> {
    return fetchJson(`/analytics/training/jobs/${encodeURIComponent(jobId)}/logs`);
  },

  getModels(): Promise<ModelVersion[]> {
    return fetchJson("/analytics/models");
  },

  getModel(modelId: string): Promise<ModelVersion> {
    return fetchJson(`/analytics/models/${encodeURIComponent(modelId)}`);
  },

  getCurrentModel(modelType: string): Promise<ModelVersion> {
    return fetchJson("/analytics/models/current", { model_type: modelType });
  },

  acceptModel(modelId: string): Promise<ModelVersion> {
    return postJson(`/analytics/models/${encodeURIComponent(modelId)}/accept`, {});
  },

  rejectModel(modelId: string): Promise<ModelVersion> {
    return postJson(`/analytics/models/${encodeURIComponent(modelId)}/reject`, {});
  },

  deployModel(modelId: string, actorUserId?: string): Promise<ModelVersion> {
    return postJson(`/analytics/models/${encodeURIComponent(modelId)}/deploy`, {
      consent_to_deploy: true,
      actor_user_id: actorUserId,
      actor_role: "admin",
    });
  },

  rollbackModel(modelId: string, actorUserId?: string): Promise<ModelVersion> {
    return postJson(`/analytics/models/${encodeURIComponent(modelId)}/rollback`, {
      actor_user_id: actorUserId,
      actor_role: "admin",
    });
  },

  getAnnotationTasks(filters?: {
    status?: string;
    dataset_id?: string;
    annotator_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<AnnotationTask[]> {
    const params: Record<string, string> = {};
    if (filters?.status) params.status = filters.status;
    if (filters?.dataset_id) params.dataset_id = filters.dataset_id;
    if (filters?.annotator_id) params.annotator_id = filters.annotator_id;
    if (filters?.limit) params.limit = String(filters.limit);
    if (filters?.offset) params.offset = String(filters.offset);
    return fetchJson("/analytics/annotation/tasks", params);
  },

  getAnnotationTask(taskId: string): Promise<AnnotationTask> {
    return fetchJson(`/analytics/annotation/tasks/${encodeURIComponent(taskId)}`);
  },

  submitLabel(taskId: string, payload: LabelSubmitRequest): Promise<{ ok: boolean }> {
    return postJson(`/analytics/annotation/tasks/${encodeURIComponent(taskId)}/label`, payload);
  },

  skipTask(taskId: string): Promise<{ ok: boolean }> {
    return postJson(`/analytics/annotation/tasks/${encodeURIComponent(taskId)}/skip`, {});
  },

  getAnnotationStats(datasetId?: string): Promise<AnnotationStats[]> {
    const params: Record<string, string> = {};
    if (datasetId) params.dataset_id = datasetId;
    return fetchJson("/analytics/annotation/stats", params);
  },

  getAnnotationGuidelines(): Promise<AnnotationGuidelines> {
    return fetchJson("/analytics/annotation/guidelines");
  },

  getEntityById(id: string, from?: string, to?: string): Promise<Entity> {
    return fetchJson(`/analytics/entities/${encodeURIComponent(id)}`, {
      ...(from ? { from } : {}),
      ...(to ? { to } : {}),
    });
  },

  getEntityAliases(id: string): Promise<EntityAlias[]> {
    return fetchJson(`/analytics/entities/${encodeURIComponent(id)}/aliases`);
  },

  getEntityMentionTimeline(id: string, from: string, to: string, bucket = "day"): Promise<EntityTimelinePoint[]> {
    return fetchJson(`/analytics/entities/${encodeURIComponent(id)}/timeline`, { from, to, bucket });
  },

  mergeEntities(sourceId: string, targetId: string, reason: string, actor?: string): Promise<MergeResult> {
    return postJson(`/analytics/entities/${encodeURIComponent(sourceId)}/merge`, {
      target_id: targetId,
      reason,
      actor: actor ?? "ui",
    });
  },

  createNormalizationRule(payload: NormalizationRuleInput): Promise<NormalizationRule> {
    return postJson("/analytics/entities/normalization-rules", payload);
  },

  getChannels(): Promise<{ channels: string[] }> {
    return fetchJson("/analytics/channels");
  },

  getAnnotationTopics(): Promise<{ topics: string[] }> {
    return fetchJson("/analytics/annotation/topics");
  },

  getMessages(
    from: string,
    to: string,
    filters?: {
      channel?: string;
      topic?: ClusterId;
      sentiment?: string;
      entity?: string;
      search?: string;
      limit?: number;
      offset?: number;
    }
  ): Promise<Message[]> {
    const params: Record<string, string> = { from, to };
    if (filters?.channel) params.channel = filters.channel;
    if (filters?.topic) params.topic = filters.topic;
    if (filters?.sentiment) params.sentiment = filters.sentiment;
    if (filters?.entity) params.entity = filters.entity;
    if (filters?.search) params.search = filters.search;
    if (filters?.limit) params.limit = String(filters.limit);
    if (filters?.offset) params.offset = String(filters.offset);
    return fetchJson("/analytics/messages", params);
  },

  getPapers(params?: {
    source_type?: string;
    source_channel?: string;
    from?: string;
    to?: string;
    parsing_status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }): Promise<ScientificPaper[]> {
    const qp: Record<string, string> = {};
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") qp[k] = String(v);
      });
    }
    return fetchJson("/analytics/papers", qp);
  },

  getPaper(id: string): Promise<PaperDetail> {
    return fetchJson(`/analytics/papers/${encodeURIComponent(id)}`);
  },

  getPaperSummary(id: string): Promise<PaperSummary> {
    return fetchJson(`/analytics/papers/${encodeURIComponent(id)}/summary`);
  },

  triggerPaperSummarize(id: string): Promise<{ status: string; paper_id: string }> {
    return postJson(`/analytics/papers/${encodeURIComponent(id)}/summarize`, undefined);
  },
};

export const getPapers = (params?: Parameters<typeof api.getPapers>[0]) => api.getPapers(params);
export const getPaper = (id: string) => api.getPaper(id);
export const getPaperSummary = (id: string) => api.getPaperSummary(id);
export const triggerPaperSummarize = (id: string) => api.triggerPaperSummarize(id);
