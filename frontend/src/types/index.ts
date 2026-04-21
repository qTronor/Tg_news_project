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
  source_status?: SourceStatus;
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
