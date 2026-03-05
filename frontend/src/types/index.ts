export interface Message {
  event_id: string;
  channel: string;
  message_id: number;
  text: string;
  date: string;
  views: number;
  forwards: number;
  topic_label?: string;
  cluster_id?: number;
  sentiment_score?: number;
  sentiment_label?: string;
  entities?: Entity[];
}

export interface Entity {
  id: string;
  text: string;
  type: "PER" | "ORG" | "LOC" | "MISC";
  normalized?: string;
  confidence?: number;
  mention_count?: number;
  topic_count?: number;
  channel_count?: number;
  trend_pct?: number;
}

export interface Topic {
  cluster_id: number;
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
}

export interface ChannelStat {
  channel: string;
  count: number;
}

export interface TopicDetail extends Topic {
  representative_messages: Message[];
  related_topics: { cluster_id: number; label: string; similarity: number }[];
  sentiment_breakdown: { positive: number; neutral: number; negative: number };
  volume_timeline: { time: string; count: number }[];
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
  community?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number;
  type: string;
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
  polling_interval_ms: number;
  theme: "light" | "dark" | "system";
  watched_channels: string[];
}
