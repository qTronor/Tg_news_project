export type ClusterId = string;
export type EntityType = "PER" | "ORG" | "LOC" | "MISC";
export type SourceStatus = "exact" | "probable" | "unknown";
export type SourceType =
  | "exact_forward"
  | "exact_reply"
  | "exact_url"
  | "quoted"
  | "inferred_semantic"
  | "earliest_in_cluster"
  | "unknown";

export interface Message {
  event_id: string;
  channel: string;
  message_id: number;
  permalink?: string | null;
  text: string;
  date: string;
  views: number;
  forwards: number;
  topic_label?: string | null;
  cluster_id?: ClusterId | null;
  sentiment_score?: number;
  sentiment_label?: string;
  sentiment_confidence?: number;
  entities?: Entity[];
  source_status?: SourceStatus;
  source_type?: SourceType;
  source_confidence?: number;
  source_event_id?: string | null;
  source_channel?: string | null;
}

export interface Entity {
  id: string;
  text: string;
  type: EntityType;
  normalized?: string;
  confidence?: number | null;
  mention_count?: number;
  topic_count?: number;
  channel_count?: number;
  trend_pct?: number;
}

export interface SourceResolution {
  resolution_kind: "exact" | "inferred";
  source_type: SourceType;
  source_confidence: number;
  source_event_id: string | null;
  source_channel: string | null;
  source_message_id: number | null;
  source_message_date: string | null;
  source_snippet: string | null;
  explanation: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

export interface PropagationLink {
  child_event_id: string;
  child_channel: string;
  child_message_id: number;
  child_message_date: string | null;
  parent_event_id: string;
  parent_channel: string | null;
  parent_message_id: number | null;
  parent_message_date: string | null;
  link_type: Exclude<SourceType, "unknown">;
  link_confidence: number;
  resolution_kind: "exact" | "inferred";
  explanation: Record<string, unknown>;
  evidence: Record<string, unknown>;
}

export interface FirstSourcePayload {
  cluster_id: ClusterId;
  source_status: SourceStatus;
  exact_source: SourceResolution | null;
  inferred_source: SourceResolution | null;
  display_source: SourceResolution | null;
  propagation_chain: PropagationLink[];
}

export type ImportanceLevel = "low" | "medium" | "high" | "critical";

export interface Topic {
  cluster_id: ClusterId;
  label: string;
  message_count: number;
  channel_count: number;
  avg_sentiment: number;
  top_entities: Entity[];
  top_keywords: string[];
  is_new: boolean;
  first_seen: string;
  last_seen: string;
  sparkline: number[];
  channels: ChannelStat[];
  source_status?: SourceStatus;
  importance_score?: number | null;
  importance_level?: ImportanceLevel | null;
  score_calculated_at?: string | null;
}

export interface ChannelStat {
  channel: string;
  count: number;
}

export interface TopicKpiMetrics {
  importance_score?: number | null;
  novelty_score?: number | null;
  growth_rate?: number | null;
}

export interface TopicTimelineAnnotation {
  time: string;
  label: string;
  description?: string | null;
}

export interface TopicGraphAnalytics {
  node_count?: number | null;
  edge_count?: number | null;
  communities_count?: number | null;
  bridge_nodes_count?: number | null;
  density?: number | null;
  top_central_entity?: Entity | null;
  top_central_channel?: ChannelStat | null;
  summary?: string | null;
}

export interface TopicSourceProvenance {
  first_seen?: string | null;
  first_source_channel?: string | null;
  source_confidence?: number | null;
  propagation_count?: number | null;
}

export interface TopicDetail extends Topic {
  representative_messages: Message[];
  related_topics: { cluster_id: ClusterId; label: string; similarity: number }[];
  sentiment_breakdown: { positive: number; neutral: number; negative: number };
  volume_timeline: { time: string; count: number }[];
  first_source?: FirstSourcePayload | null;
  summary?: string | null;
  status?: "new" | "growing" | "declining" | "stable" | SourceStatus | null;
  kpi_metrics?: TopicKpiMetrics | null;
  timeline_annotations?: TopicTimelineAnnotation[];
  graph_analytics?: TopicGraphAnalytics | null;
  source_provenance?: TopicSourceProvenance | null;
  score_breakdown?: Record<string, unknown> | null;
}

export interface TopicTimelineApiEvent {
  event_type: string;
  event_time: string;
  bucket_start?: string | null;
  severity?: number | null;
  summary: string;
  details?: Record<string, unknown>;
  created_at?: string | null;
}

export interface TopicTimelineApiPoint {
  bucket_start: string;
  bucket_end: string;
  message_count: number;
  unique_channel_count: number;
  top_entities: Array<Record<string, unknown>>;
  sentiment: Record<string, number>;
  new_channels: string[];
  event_ids: string[];
  calculated_at?: string | null;
}

export interface TopicTimelineApiResponse {
  cluster_id: ClusterId;
  bucket_size: string;
  points: TopicTimelineApiPoint[];
  events: TopicTimelineApiEvent[];
  generated_at?: string | null;
  storage_status?: string;
}

export interface TopicGraphMetricsApiNode {
  id: string;
  label: string;
  type: string;
  degree_centrality?: number;
  betweenness_centrality?: number;
  pagerank?: number;
  community_id?: number | null;
  is_bridge?: boolean;
  bridge_score?: number;
  weight?: number;
}

export interface TopicGraphMetricsApiSummary {
  node_count: number;
  edge_count: number;
  density: number;
  average_degree?: number;
  component_count?: number;
  largest_component_size?: number;
  community_count?: number;
  is_small_graph?: boolean;
}

export interface TopicGraphMetricsApiResponse {
  cluster_id: ClusterId;
  window?: { from: string; to: string };
  algorithm_version?: string;
  graph?: {
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  };
  summary: TopicGraphMetricsApiSummary;
  top_entities: Entity[];
  top_channels: Array<ChannelStat & { pagerank?: number }>;
  bridge_nodes: TopicGraphMetricsApiNode[];
  communities?: Array<Record<string, unknown>>;
  nodes?: TopicGraphMetricsApiNode[];
}

export type TopicComparisonClassification =
  | "same_topic"
  | "related_topics"
  | "different_topics"
  | "possible_subtopic_split";

export interface TopicComparisonComponent {
  score: number;
  weight: number;
  contribution: number;
  label: string;
}

export interface TopicComparisonSharedEntity {
  id: string;
  text: string;
  type?: EntityType | string | null;
  a_mentions: number;
  b_mentions: number;
  min_mentions: number;
}

export interface TopicComparisonSharedChannel {
  channel: string;
  a_count: number;
  b_count: number;
  min_count: number;
}

export interface TopicComparisonResult {
  cluster_a_id: ClusterId;
  cluster_b_id: ClusterId;
  algorithm_version: string;
  similarity_score: number;
  classification: TopicComparisonClassification;
  is_same_topic: boolean;
  breakdown: Record<string, TopicComparisonComponent>;
  evidence: {
    entities: {
      score: number;
      shared: TopicComparisonSharedEntity[];
      a_count: number;
      b_count: number;
    };
    channels: {
      score: number;
      shared: TopicComparisonSharedChannel[];
      a_count: number;
      b_count: number;
    };
    time: {
      score: number;
      overlap_coefficient: number;
      overlap_seconds: number;
      gap_seconds: number | null;
    };
    messages: {
      score: number;
      shared_event_ids: string[];
      shared_fingerprints: string[];
    };
    sentiment: {
      score: number;
      delta: number;
      a_avg_signed: number;
      b_avg_signed: number;
    };
    embedding: {
      score: number | null;
      available: boolean;
    };
  };
  topic_a: {
    cluster_id: ClusterId;
    label: string | null;
    message_count: number;
    first_seen: string | null;
    last_seen: string | null;
    avg_sentiment: number;
    entity_count: number;
    channel_count: number;
  };
  topic_b: {
    cluster_id: ClusterId;
    label: string | null;
    message_count: number;
    first_seen: string | null;
    last_seen: string | null;
    avg_sentiment: number;
    entity_count: number;
    channel_count: number;
  };
  explanation: {
    summary: string;
    positive_factors: string[];
    negative_factors: string[];
    subtopic_split_signals: string[];
  };
  window?: {
    from: string;
    to: string;
  };
  cached?: boolean;
}

export interface SentimentPoint {
  time: string;
  positive: number;
  neutral: number;
  negative: number;
}

export interface OverviewStats {
  total_messages: number;
  messages_change_pct: number;
  new_topics: number;
  topics_change: number;
  active_channels: number;
  avg_sentiment: number;
}

export interface GraphNode {
  id: string;
  label: string;
  type: "topic" | "channel" | "entity_per" | "entity_org" | "entity_loc" | "message";
  weight: number;
  community?: number | null;
  channel?: string;
  message_id?: number;
  message_date?: string;
  cluster_id?: ClusterId | null;
  permalink?: string | null;
  source_status?: SourceStatus;
  source_event_id?: string | null;
  source_channel?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  type: string;
  confidence?: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface TimeRange {
  from: string;
  to: string;
}

export interface AppConfig {
  api_base_url: string;
  auth_base_url: string;
  polling_interval_ms: number;
  theme: "light" | "dark" | "system";
  watched_channels: string[];
}

export type UserRole = "admin" | "user";
export type UserSourceStatus =
  | "validating"
  | "validation_failed"
  | "live_enabled"
  | "backfilling"
  | "ready";

export interface UserProfile {
  id: string;
  email: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface ReactionInfo {
  message_event_id: string;
  likes: number;
  dislikes: number;
  user_reaction: "like" | "dislike" | null;
}

export interface AuditLogEntry {
  id: string;
  admin_id: string | null;
  admin_username: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface ChannelVisibility {
  channel_name: string;
  is_visible: boolean;
  updated_at: string | null;
}

export interface LlmEnrichmentResponse {
  status: "ok" | "error" | "budget_exhausted" | "pending";
  result: Record<string, unknown> | null;
  cached?: boolean;
  model?: { provider: string; name: string };
  prompt_version?: string;
  language?: string;
  analysis_mode?: string;
  tokens?: { input: number; output: number };
  cost_usd?: number;
  latency_ms?: number;
  generated_at?: string | null;
  is_llm_generated: boolean;
  message?: string | null;
}

export interface ClusterSummaryResult {
  summary: string;
  key_points: string[];
}

export interface ClusterExplanationResult {
  why_important: string;
  drivers: { name: string; weight: number; explanation: string }[];
}

export interface NoveltyExplanationResult {
  novelty_verdict: "new" | "ongoing" | "resurgent";
  rationale: string;
}

export interface UserTelegramChannel {
  channel_name: string;
  input_value: string | null;
  telegram_url: string | null;
  telegram_channel_id: number | null;
  requested_start_date: string | null;
  historical_limit_date: string;
  status: UserSourceStatus;
  validation_status: "pending" | "validated" | "failed";
  validation_error: string | null;
  live_enabled: boolean;
  backfill_total_days: number;
  backfill_completed_days: number;
  backfill_failed_days: number;
  backfill_pending_days: number;
  backfill_running_days: number;
  backfill_retrying_days: number;
  backfill_messages_published: number;
  backfill_last_completed_date: string | null;
  last_live_collected_at: string | null;
  added_at: string;
  added_by_user_id: string | null;
  first_message_at: string | null;
  first_message_event_id: string | null;
  first_message_available: boolean;
  raw_message_count: number;
  feed_path: string | null;
}
