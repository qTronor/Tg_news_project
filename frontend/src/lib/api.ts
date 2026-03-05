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

const BASE = config.apiBaseUrl;
const TIMEOUT_MS = 5_000;

async function fetchJson<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, BASE);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(url.toString(), { signal: controller.signal });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return await res.json();
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`API timeout: ${url.pathname} did not respond within ${TIMEOUT_MS / 1000}s`);
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
    return fetchJson("/analytics/overview/clusters", { from, to, ...(channel ? { channel } : {}) });
  },

  getClusterDetail(clusterId: number, from: string, to: string): Promise<TopicDetail> {
    return fetchJson(`/analytics/clusters/${clusterId}`, { from, to });
  },

  getClusterDocuments(clusterId: number, from: string, to: string, limit = 50, offset = 0): Promise<Message[]> {
    return fetchJson(`/analytics/clusters/${clusterId}/documents`, {
      from, to, limit: String(limit), offset: String(offset),
    });
  },

  getRelatedClusters(clusterId: number, from: string, to: string): Promise<{ cluster_id: number; label: string; similarity: number }[]> {
    return fetchJson(`/analytics/clusters/${clusterId}/related`, { from, to });
  },

  getTopEntities(from: string, to: string, entityType?: string, clusterId?: number): Promise<Entity[]> {
    return fetchJson("/analytics/entities/top", {
      from, to,
      ...(entityType ? { entity_type: entityType } : {}),
      ...(clusterId ? { cluster_id: String(clusterId) } : {}),
    });
  },

  getSentimentDynamics(from: string, to: string, bucket = "hour", channel?: string, clusterId?: number): Promise<SentimentPoint[]> {
    return fetchJson("/analytics/sentiment/dynamics", {
      from, to, bucket,
      ...(channel ? { channel } : {}),
      ...(clusterId ? { cluster_id: String(clusterId) } : {}),
    });
  },

  getGraph(from: string, to: string, focusId?: string, depth = 2): Promise<GraphData> {
    return fetchJson("/analytics/graph", {
      from, to, depth: String(depth),
      ...(focusId ? { focus: focusId } : {}),
    });
  },

  getMessages(from: string, to: string, filters?: {
    channel?: string;
    topic?: string;
    sentiment?: string;
    entity?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }): Promise<Message[]> {
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
