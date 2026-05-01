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
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
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
    return fetchJson("/analytics/overview/clusters", {
      from,
      to,
      ...(channel ? { channel } : {}),
    });
  },

  getClusterDetail(clusterId: ClusterId, from: string, to: string): Promise<TopicDetail> {
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}`, { from, to });
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
    return fetchJson(`/analytics/clusters/${encodeURIComponent(clusterId)}/related`, {
      from,
      to,
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
};
