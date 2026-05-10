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

export interface EntityAlias {
  alias: string;
  source: string;
  confidence: number;
  is_primary: boolean;
  language?: string | null;
  created_at?: string | null;
}

export interface EntityTimelinePoint {
  time: string;
  mention_count: number;
}

export interface MergeResult {
  source_id: string;
  target_id: string;
  transferred_aliases: number;
  repointed_ner_results: number;
}

export interface NormalizationRuleInput {
  rule_type: "alias" | "abbreviation" | "regex" | "merge";
  pattern: string;
  replacement?: string;
  entity_type?: string;
  language?: string;
  target_canonical_id?: string;
  priority?: number;
  created_by?: string;
}

export interface NormalizationRule extends NormalizationRuleInput {
  id: string;
  created_at: string;
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
  canonical_name?: string;
  aliases?: EntityAlias[];
  source_model?: string;
  first_seen_at?: string;
  last_seen_at?: string;
  wikidata_id?: string | null;
  merged_into_id?: string | null;
  description?: string | null;
  language?: string | null;
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
  novelty_score?: number | null;
  novelty_status?: TopicNoveltyStatus | null;
  novelty_explanation?: Record<string, unknown> | null;
  confidence_score?: number | null;
  stability_score?: number | null;
  review?: TopicReviewLabel | null;
  model?: TopicModelRunInfo | null;
}

export interface TopicReviewLabel {
  label: string;
  source: "auto" | "human" | "merged" | "split";
  status: "active" | "superseded" | "rejected" | "noise" | "uncertain";
  confidence?: number | null;
  created_at?: string | null;
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

export type TopicNoveltyStatus =
  | "new"
  | "continuation"
  | "merged"
  | "split"
  | "uncertain"
  | "noise";

export interface TopicNoveltyPayload {
  cluster_id: ClusterId;
  run_id?: string | null;
  novelty_score: number;
  novelty_status: TopicNoveltyStatus;
  nearest_topic_id?: ClusterId | null;
  features: Record<string, number>;
  explanation: {
    summary?: string;
    reasons?: string[];
    new_entities?: string[];
    nearest_topic_id?: string | null;
    formula?: Record<string, unknown>;
  };
  calculated_at?: string | null;
  algorithm_version?: string | null;
}

export interface TopicSimilarityHistoryItem {
  cluster_id: ClusterId;
  semantic_similarity: number;
  entity_overlap: number;
  channel_overlap: number;
  keyword_overlap: number;
  overall_similarity: number;
  first_seen?: string | null;
  last_seen?: string | null;
  message_count: number;
  keywords: string[];
  top_entities: Array<{ id: string; text: string; mention_count: number }>;
  evidence?: Record<string, unknown>;
  calculated_at?: string | null;
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
  novelty?: TopicNoveltyPayload | null;
  similar_history?: TopicSimilarityHistoryItem[];
  centroid?: number[] | null;
  top_channels?: ChannelStat[];
  time_distribution?: { bucket_id: string; count: number }[];
  confidence_score?: number | null;
  stability_score?: number | null;
  review?: TopicReviewLabel | null;
  model?: TopicModelRunInfo | null;
}

export type TopicReviewReason =
  | "new_topic"
  | "low_confidence"
  | "high_outlier_ratio"
  | "history_conflict"
  | "rapid_growth"
  | "manual_request";

export type TopicReviewStatus = "pending" | "in_progress" | "completed" | "rejected" | "deferred";

export interface TopicReviewTask {
  id: string;
  cluster_id: ClusterId;
  run_id: string | null;
  reason: TopicReviewReason;
  status: TopicReviewStatus;
  priority: number;
  signals: Record<string, unknown>;
  requested_by: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string | null;
  completed_at: string | null;
  active_label: string | null;
  label_source: TopicReviewLabel["source"] | null;
  label_status: TopicReviewLabel["status"] | null;
  topic: TopicDetail | null;
}

export interface TopicReviewActionRequest {
  actor_user_id?: string;
  actor_username?: string;
  label?: string;
  description?: string;
  confidence?: number;
  target_cluster_id?: string;
  child_labels?: string[];
  event_ids?: string[];
  reason?: string;
  comment?: string;
}

export interface TopicModelRunInfo {
  run_id?: string | null;
  model_version?: string | null;
  config_hash?: string | null;
  dataset_version?: string | null;
  embedding_model?: string | null;
  created_at?: string | null;
  metrics?: Record<string, unknown>;
  config?: Record<string, unknown>;
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

export interface TopicExperiment {
  id: string;
  name: string;
  description?: string | null;
  dataset_version: string;
  dataset_version_id?: string | null;
  window_start: string;
  window_end: string;
  channels: string[];
  seed: number;
  status: "created" | "running" | "completed" | "failed";
  created_at: string;
  updated_at?: string | null;
  run_count: number;
  completed_run_count: number;
}

export interface TopicExperimentRun {
  run_id: string;
  cluster_run_id?: string | null;
  model_key: string;
  model_name: string;
  is_baseline: boolean;
  status: "queued" | "running" | "completed" | "failed" | "skipped";
  error_message?: string | null;
  metrics: Record<string, number | null | Record<string, unknown>>;
  clusters_url?: string | null;
}

export interface TopicExperimentMetrics {
  experiment_id: string;
  runs: TopicExperimentRun[];
}

export interface TopicExperimentRunRequest {
  name?: string;
  description?: string;
  from: string;
  to: string;
  dataset_version_id?: string;
  channels?: string[];
  models: string[];
  embedding_model?: string;
  seed?: number;
  dataset_version?: string;
  max_messages?: number;
  n_topics?: number;
}

export interface TopicExperimentRunResponse {
  experiment_id: string;
  status: string;
  run_ids: string[];
  runner_command: string;
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
  novelty_status?: TopicNoveltyStatus | null;
  novelty_score?: number | null;
  is_first_source?: boolean;
  is_focus_source?: boolean;
  is_self_source?: boolean;
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

export interface TopicSummaryBundle {
  public_cluster_id: string;
  language: string;
  model: { provider: string; name: string };
  generated_at: string;
  summaries: {
    short?: {
      summary: string;
      key_points: string[];
      status: string;
      prompt_version: string | null;
    };
    timeline?: {
      events: { when: string; what: string; source_channel?: string }[];
      status: string;
    };
    key_actors?: {
      actors: { name: string; role: string; why_matters: string; mention_count: number }[];
      status: string;
    };
    why_important?: {
      why_important: string;
      drivers: { name: string; weight: number; explanation: string }[];
      status: string;
    };
    what_changed?: {
      summary: string;
      changes: { period: string; change_description: string; severity: number }[];
      status: string;
    };
    novelty?: {
      novelty_verdict: "new" | "ongoing" | "resurgent";
      rationale: string;
      status: string;
    };
  };
}

export interface ClusterExplanationResult {
  why_important: string;
  drivers: { name: string; weight: number; explanation: string }[];
}

export interface NoveltyExplanationResult {
  novelty_verdict: "new" | "ongoing" | "resurgent";
  rationale: string;
}

// ── Annotation / Dataset types ────────────────────────────────────────────────

export type AnnotationQuality = "useful" | "noise" | "duplicate";
export type AnnotationSplit = "train" | "validation" | "test" | "temporal_test" | "unassigned";
export type DatasetStatus = "building" | "ready" | "archived";
export type TaskStatus = "pending" | "in_progress" | "completed" | "skipped";

export interface AnnotationLabel {
  broad_topic: string | null;
  storyline: string | null;
  is_new_storyline: boolean | null;
  quality: AnnotationQuality;
  sentiment: string | null;
  entities: Array<{ text: string; type: string }>;
  comment: string | null;
  annotator_confidence: number | null;
}

export interface AnnotationItem {
  id: string;
  event_id: string;
  channel: string;
  message_id: number;
  text: string;
  cleaned_text: string | null;
  message_date: string;
  word_count: number;
  language: string | null;
  split: AnnotationSplit;
  cluster_id: string | null;
  auto_topic_label: string | null;
  dataset_version_id: string | null;
  dataset_version_name: string | null;
}

export interface AnnotationTask {
  id: string;
  status: TaskStatus;
  priority: number;
  assigned_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  annotator_username: string | null;
  item: AnnotationItem;
  label: AnnotationLabel | null;
}

export interface DatasetVersion {
  id: string;
  name: string;
  description: string | null;
  language: string;
  window_start: string;
  window_end: string;
  channels: string[];
  min_word_count: number;
  dedup_strategy: string;
  total_items: number;
  annotated_count: number;
  annotation_progress: number;
  status: DatasetStatus;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
  validation?: DatasetValidationReport;
}

export interface AnnotationStats {
  dataset_version_id: string;
  dataset_version_name: string;
  total_items: number;
  annotated_items: number;
  pending_items: number;
  skipped_items: number;
  annotation_progress: number;
  quality_distribution: { useful: number; noise: number; duplicate: number };
  distinct_topics: number;
}

export interface DatasetBuildRequest {
  name: string;
  description?: string;
  window_start: string;
  window_end: string;
  channels?: string[];
  min_word_count?: number;
  dedup_strategy?: string;
  languages?: string[];
  created_by?: string;
}

export interface LabelSubmitRequest {
  user_id: string;
  username: string;
  broad_topic?: string | null;
  storyline?: string | null;
  is_new_storyline?: boolean | null;
  quality: AnnotationQuality;
  sentiment?: string | null;
  entities?: Array<{ text: string; type: string }>;
  comment?: string | null;
  annotator_confidence?: number | null;
}

export interface AnnotationGuidelines {
  id: string;
  version: string;
  title: string;
  content: string;
  created_at: string;
}

export type TrainingTaskType =
  | "topic_classification"
  | "sentiment_classification"
  | "embedding_finetuning"
  | "ner_finetuning";
export type DatasetValidationStatus = "valid" | "warning" | "invalid";
export type TrainingJobStatus =
  | "draft"
  | "waiting_for_consent"
  | "queued"
  | "running"
  | "evaluating"
  | "completed"
  | "failed"
  | "cancelled";
export type ModelVersionStatus = "candidate" | "accepted" | "rejected" | "deployed" | "archived" | "failed";
export type ModelType = "topic_classifier" | "sentiment_classifier" | "embedding_model" | "ner_model";

export interface DatasetValidationReport {
  id?: string;
  dataset_id: string;
  dataset_name?: string | null;
  task_type: TrainingTaskType;
  status: DatasetValidationStatus;
  dataset_size: number;
  labeled_items: number;
  label_distribution: Record<string, number>;
  split_distribution: Record<string, number>;
  empty_text_count: number;
  warnings: string[];
  errors: string[];
  metrics: string[];
  created_at?: string;
}

export interface TrainingPlan {
  dataset_id: string;
  dataset_name: string;
  dataset_size: number;
  task_type: TrainingTaskType;
  label_distribution: Record<string, number>;
  split: Record<string, number>;
  base_model: string;
  training_config: Record<string, unknown>;
  metrics: string[];
  warnings: string[];
  validation_status: DatasetValidationStatus;
  will_auto_deploy: false;
  production_notice: string;
}

export interface TrainingJob {
  id: string;
  dataset_id: string;
  dataset_name: string;
  task_type: TrainingTaskType;
  base_model: string;
  training_config: Record<string, unknown>;
  status: TrainingJobStatus;
  consent_to_train_by: string | null;
  consent_to_train_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
  candidate_model: {
    id: string;
    version: string;
    status: ModelVersionStatus;
    metrics: Record<string, unknown>;
  } | null;
  evaluations?: Array<{
    split: string;
    metrics: Record<string, unknown>;
    confusion_matrix: Record<string, unknown>;
    created_at: string;
  }>;
}

export interface TrainingJobLog {
  id: string;
  level: "debug" | "info" | "warning" | "error";
  message: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ModelVersion {
  id: string;
  training_job_id: string | null;
  model_name: string;
  model_type: ModelType;
  base_model: string;
  version: string;
  artifact_path: string;
  metrics: Record<string, unknown>;
  status: ModelVersionStatus;
  created_at: string;
  deployed_at: string | null;
  deployed_by: string | null;
  evaluations?: Array<{
    dataset_id: string;
    split: string;
    metrics: Record<string, unknown>;
    confusion_matrix: Record<string, unknown>;
    created_at: string;
  }>;
  deployment_history?: Array<{
    previous_model_version_id: string | null;
    deployed_by: string | null;
    deployed_at: string;
    rollback_available: boolean;
    metadata: Record<string, unknown>;
  }>;
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

export interface ScientificPaper {
  id: string;
  source_message_id: string;
  source_channel: string;
  source_url: string | null;
  source_type: 'arxiv' | 'openreview' | 'doi' | 'pdf_url' | 'telegram_file' | 'webpage';
  title: string | null;
  authors: string[];
  abstract: string | null;
  detected_at: string;
  parsing_status: 'detected' | 'parsing' | 'parsed' | 'partial' | 'failed';
  has_summary: boolean;
  short_summary: string | null;
  created_at: string;
}

export interface PaperDetail extends ScientificPaper {
  telegram_file_id: string | null;
  published_at: string | null;
  has_text: boolean;
  updated_at: string | null;
  summary?: PaperSummary;
}

export interface PaperSummaryJson {
  title?: string;
  authors?: string[];
  abstract_summary?: string;
  research_problem?: string;
  main_contribution?: string;
  method?: string;
  datasets?: string[];
  metrics?: string[];
  experiments?: string;
  results?: string;
  limitations?: string;
  keywords?: string[];
  paper_type?: string;
  short_summary?: string;
}

export interface PaperSummary {
  id: string;
  paper_id: string;
  model_name: string;
  prompt_version: string;
  summary_json: PaperSummaryJson;
  short_summary: string | null;
  created_at: string;
}
