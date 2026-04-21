import type {
  ClusterId,
  Entity,
  FirstSourcePayload,
  GraphData,
  Message,
  OverviewStats,
  SentimentPoint,
  Topic,
  TopicDetail,
} from "@/types";

const NOW = new Date();

function hoursAgo(hours: number) {
  return new Date(NOW.getTime() - hours * 3_600_000).toISOString();
}

function clusterId(seed: number): ClusterId {
  return `demo:${seed}`;
}

function clusterSeed(value: ClusterId): number {
  return parseInt(value.split(":").pop() || "0", 10);
}

function firstSourceForCluster(id: ClusterId): FirstSourcePayload {
  const seed = clusterSeed(id);
  const baseDate = hoursAgo(8 + seed);

  if (seed === 1) {
    const exact = {
      resolution_kind: "exact" as const,
      source_type: "exact_forward" as const,
      source_confidence: 1,
      source_event_id: "agency:101",
      source_channel: "AgencyWire",
      source_message_id: 101,
      source_message_date: baseDate,
      source_snippet: "AgencyWire published the first bulletin before resharing began.",
      explanation: {
        summary: "Telegram forward metadata points to a concrete upstream message.",
      },
      evidence: {
        forward_from_channel_id: 1001,
        forward_from_message_id: 101,
      },
    };
    const inferred = {
      resolution_kind: "inferred" as const,
      source_type: "earliest_in_cluster" as const,
      source_confidence: 0.42,
      source_event_id: "agency:101",
      source_channel: "AgencyWire",
      source_message_id: 101,
      source_message_date: baseDate,
      source_snippet: "AgencyWire published the first bulletin before resharing began.",
      explanation: {
        summary: "Fallback to earliest cluster message.",
      },
      evidence: { fallback: "earliest_in_cluster" },
    };
    return {
      cluster_id: id,
      source_status: "exact",
      exact_source: exact,
      inferred_source: inferred,
      display_source: exact,
      propagation_chain: [
        {
          child_event_id: "rbc:201",
          child_channel: "RBC",
          child_message_id: 201,
          child_message_date: hoursAgo(6),
          parent_event_id: "agency:101",
          parent_channel: "AgencyWire",
          parent_message_id: 101,
          parent_message_date: baseDate,
          link_type: "exact_forward",
          link_confidence: 1,
          resolution_kind: "exact",
          explanation: { summary: "Forward edge" },
          evidence: { forward_from_message_id: 101 },
        },
      ],
    };
  }

  if (seed === 2) {
    const exact = {
      resolution_kind: "exact" as const,
      source_type: "unknown" as const,
      source_confidence: 0,
      source_event_id: null,
      source_channel: null,
      source_message_id: null,
      source_message_date: null,
      source_snippet: null,
      explanation: { summary: "No strict source metadata was found." },
      evidence: { reason: "unknown" },
    };
    const inferred = {
      resolution_kind: "inferred" as const,
      source_type: "quoted" as const,
      source_confidence: 0.77,
      source_event_id: "desk:302",
      source_channel: "DeskNews",
      source_message_id: 302,
      source_message_date: baseDate,
      source_snippet: "DeskNews appears to be the earliest quoted formulation of the story.",
      explanation: {
        summary: "Quoted fragment and shared entities matched an earlier message.",
      },
      evidence: {
        quoted_fragment_match: true,
        entity_overlap: 0.66,
      },
    };
    return {
      cluster_id: id,
      source_status: "probable",
      exact_source: exact,
      inferred_source: inferred,
      display_source: inferred,
      propagation_chain: [
        {
          child_event_id: "market:401",
          child_channel: "MarketWatch",
          child_message_id: 401,
          child_message_date: hoursAgo(5),
          parent_event_id: "desk:302",
          parent_channel: "DeskNews",
          parent_message_id: 302,
          parent_message_date: baseDate,
          link_type: "quoted",
          link_confidence: 0.77,
          resolution_kind: "inferred",
          explanation: { summary: "Quoted propagation edge" },
          evidence: { quoted_fragment_match: true },
        },
      ],
    };
  }

  return {
    cluster_id: id,
    source_status: "unknown",
    exact_source: {
      resolution_kind: "exact",
      source_type: "unknown",
      source_confidence: 0,
      source_event_id: null,
      source_channel: null,
      source_message_id: null,
      source_message_date: null,
      source_snippet: null,
      explanation: { summary: "No strict source metadata was found." },
      evidence: { reason: "unknown" },
    },
    inferred_source: {
      resolution_kind: "inferred",
      source_type: "unknown",
      source_confidence: 0,
      source_event_id: null,
      source_channel: null,
      source_message_id: null,
      source_message_date: null,
      source_snippet: null,
      explanation: { summary: "No probable upstream message cleared the threshold." },
      evidence: { reason: "unknown" },
    },
    display_source: null,
    propagation_chain: [],
  };
}

function makeMessages(topic: Topic, count: number): Message[] {
  const seed = clusterSeed(topic.cluster_id);
  const firstSource = firstSourceForCluster(topic.cluster_id);
  return Array.from({ length: count }, (_, index) => ({
    event_id: `${topic.label.toLowerCase().replace(/\s+/g, "-")}:${seed * 100 + index}`,
    channel: topic.channels[index % topic.channels.length]?.channel || "Channel",
    message_id: seed * 100 + index,
    text: `${topic.label} update ${index + 1}: new details continue to propagate across channels.`,
    date: hoursAgo(seed + index),
    views: 1_000 + seed * 150 + index * 25,
    forwards: 50 + seed * 10 + index * 3,
    topic_label: topic.label,
    cluster_id: topic.cluster_id,
    sentiment_score: seed === 1 ? 0.46 : seed === 2 ? -0.18 : 0.04,
    sentiment_label: seed === 1 ? "Positive" : seed === 2 ? "Negative" : "Neutral",
    sentiment_confidence: 0.82,
    source_status: firstSource.source_status,
    source_type: firstSource.display_source?.source_type || "unknown",
    source_confidence: firstSource.display_source?.source_confidence || 0,
    source_event_id: firstSource.display_source?.source_event_id || null,
    source_channel: firstSource.display_source?.source_channel || null,
    entities: topic.top_entities.slice(0, 2),
  }));
}

export const mockOverview: OverviewStats = {
  total_messages: 12_847,
  messages_change_pct: 14.3,
  new_topics: 2,
  topics_change: 1,
  active_channels: 18,
  avg_sentiment: 0.11,
};

export const mockTopics: Topic[] = [
  {
    cluster_id: clusterId(1),
    label: "Central Bank Rate",
    message_count: 342,
    channel_count: 12,
    avg_sentiment: 0.46,
    top_entities: [
      { id: "ORG:central-bank", text: "Central Bank", type: "ORG", mention_count: 210 },
      { id: "PER:governor", text: "Governor", type: "PER", mention_count: 128 },
      { id: "LOC:moscow", text: "Moscow", type: "LOC", mention_count: 87 },
    ],
    top_keywords: ["rate", "inflation", "bank"],
    is_new: true,
    first_seen: hoursAgo(10),
    last_seen: hoursAgo(1),
    sparkline: [2, 4, 8, 11, 16, 23, 29, 26, 22, 16, 11, 7],
    channels: [
      { channel: "RBC", count: 92 },
      { channel: "AgencyWire", count: 76 },
      { channel: "MarketWatch", count: 41 },
    ],
    source_status: "exact",
  },
  {
    cluster_id: clusterId(2),
    label: "Election Coalition Talks",
    message_count: 198,
    channel_count: 8,
    avg_sentiment: -0.18,
    top_entities: [
      { id: "PER:chancellor", text: "Chancellor", type: "PER", mention_count: 134 },
      { id: "ORG:parliament", text: "Parliament", type: "ORG", mention_count: 92 },
      { id: "LOC:berlin", text: "Berlin", type: "LOC", mention_count: 65 },
    ],
    top_keywords: ["election", "coalition", "vote"],
    is_new: false,
    first_seen: hoursAgo(30),
    last_seen: hoursAgo(2),
    sparkline: [9, 12, 14, 17, 19, 16, 12, 10, 8, 6, 5, 4],
    channels: [
      { channel: "DeskNews", count: 71 },
      { channel: "WorldBrief", count: 53 },
      { channel: "MarketWatch", count: 29 },
    ],
    source_status: "probable",
  },
  {
    cluster_id: clusterId(3),
    label: "AI Safety Regulation",
    message_count: 154,
    channel_count: 6,
    avg_sentiment: 0.09,
    top_entities: [
      { id: "ORG:eu", text: "EU", type: "ORG", mention_count: 119 },
      { id: "ORG:openai", text: "OpenAI", type: "ORG", mention_count: 78 },
      { id: "LOC:brussels", text: "Brussels", type: "LOC", mention_count: 44 },
    ],
    top_keywords: ["ai", "regulation", "safety"],
    is_new: true,
    first_seen: hoursAgo(18),
    last_seen: hoursAgo(3),
    sparkline: [0, 2, 5, 7, 12, 18, 24, 21, 18, 14, 10, 6],
    channels: [
      { channel: "TechDaily", count: 64 },
      { channel: "RBC", count: 39 },
      { channel: "PolicyNow", count: 22 },
    ],
    source_status: "unknown",
  },
];

export function mockTopicDetail(id: ClusterId): TopicDetail {
  const topic = mockTopics.find((item) => item.cluster_id === id) || mockTopics[0];
  const seed = clusterSeed(topic.cluster_id);
  const firstSource = firstSourceForCluster(topic.cluster_id);
  return {
    ...topic,
    representative_messages: makeMessages(topic, 5),
    related_topics: mockTopics
      .filter((item) => item.cluster_id !== topic.cluster_id)
      .slice(0, 3)
      .map((item, index) => ({
        cluster_id: item.cluster_id,
        label: item.label,
        similarity: Number((0.46 + index * 0.11).toFixed(2)),
      })),
    sentiment_breakdown: {
      positive: topic.avg_sentiment > 0 ? 48 : 16,
      neutral: 24,
      negative: topic.avg_sentiment < 0 ? 46 : 18,
    },
    volume_timeline: Array.from({ length: 12 }, (_, index) => ({
      time: hoursAgo(12 - index),
      count: seed === 2 ? 46 - index * 3 : 4 + index * 3,
    })),
    first_source: firstSource,
    summary:
      seed === 1
        ? "Fast-moving monetary policy discussion with broad channel pickup and an exact upstream source."
        : seed === 2
          ? "Political coalition story is cooling after an earlier peak, with source attribution inferred from quoted fragments."
          : "Regulation discussion is still forming; source metadata and graph analytics are partially available.",
    status: seed === 1 ? "growing" : seed === 2 ? "declining" : "new",
    kpi_metrics: {
      importance_score: seed === 1 ? 0.86 : seed === 2 ? 0.61 : null,
      novelty_score: seed === 1 ? 0.72 : seed === 2 ? 0.28 : 0.67,
      growth_rate: seed === 1 ? 0.34 : seed === 2 ? -0.16 : 0.18,
    },
    timeline_annotations:
      seed === 3
        ? []
        : [
            {
              time: hoursAgo(7),
              label: seed === 1 ? "Forward spike" : "Quote cascade",
              description:
                seed === 1
                  ? "Exact forward metadata appeared across major channels."
                  : "Several channels reused the same quoted formulation.",
            },
          ],
    graph_analytics:
      seed === 3
        ? null
        : {
            node_count: seed === 1 ? 38 : 27,
            edge_count: seed === 1 ? 74 : 41,
            communities_count: seed === 1 ? 4 : 3,
            bridge_nodes_count: seed === 1 ? 5 : 2,
            density: seed === 1 ? 0.105 : 0.117,
            top_central_entity: topic.top_entities[0],
            top_central_channel: topic.channels[0],
            summary:
              seed === 1
                ? "Dense cross-channel propagation around the policy source and two entity hubs."
                : "Lower density network with a small number of channel bridges.",
          },
    source_provenance: {
      first_seen: firstSource.display_source?.source_message_date || topic.first_seen,
      first_source_channel: firstSource.display_source?.source_channel || null,
      source_confidence: firstSource.display_source?.source_confidence ?? null,
      propagation_count: firstSource.propagation_chain.length,
    },
  };
}

export const mockEntities: Entity[] = [
  {
    id: "ORG:central-bank",
    text: "Central Bank",
    type: "ORG",
    normalized: "Central Bank",
    mention_count: 1247,
    topic_count: 5,
    channel_count: 23,
    trend_pct: 34,
  },
  {
    id: "PER:governor",
    text: "Governor",
    type: "PER",
    normalized: "Governor",
    mention_count: 843,
    topic_count: 3,
    channel_count: 18,
    trend_pct: 17,
  },
  {
    id: "LOC:berlin",
    text: "Berlin",
    type: "LOC",
    mention_count: 622,
    topic_count: 2,
    channel_count: 12,
    trend_pct: -8,
  },
  {
    id: "ORG:eu",
    text: "EU",
    type: "ORG",
    mention_count: 598,
    topic_count: 4,
    channel_count: 15,
    trend_pct: 22,
  },
  {
    id: "MISC:bitcoin",
    text: "Bitcoin",
    type: "MISC",
    mention_count: 481,
    topic_count: 2,
    channel_count: 11,
    trend_pct: 9,
  },
];

export const mockSentiment: SentimentPoint[] = Array.from({ length: 12 }, (_, index) => ({
  time: hoursAgo(12 - index),
  positive: 40 + index * 3,
  neutral: 55 - index,
  negative: 18 + (index % 4) * 2,
}));

export const mockMessages: Message[] = mockTopics
  .flatMap((topic) => makeMessages(topic, 6))
  .sort((left, right) => new Date(right.date).getTime() - new Date(left.date).getTime());

export const mockGraph: GraphData = {
  nodes: [
    ...mockTopics.map((topic) => ({
      id: `topic-${topic.cluster_id}`,
      label: topic.label,
      type: "topic" as const,
      weight: topic.message_count,
      community: null,
      source_status: topic.source_status,
    })),
    { id: "ch-RBC", label: "RBC", type: "channel" as const, weight: 92, community: null },
    { id: "ch-AgencyWire", label: "AgencyWire", type: "channel" as const, weight: 76, community: null },
    {
      id: "ent-ORG:central-bank",
      label: "Central Bank",
      type: "entity_org" as const,
      weight: 210,
      community: null,
    },
    {
      id: "ent-PER:governor",
      label: "Governor",
      type: "entity_per" as const,
      weight: 128,
      community: null,
    },
    {
      id: "msg-agency:101",
      label: "AgencyWire bulletin",
      type: "message" as const,
      weight: 3,
      community: null,
      channel: "AgencyWire",
      message_id: 101,
      message_date: hoursAgo(8),
      source_status: "exact" as const,
    },
  ],
  edges: [
    {
      source: `topic-${clusterId(1)}`,
      target: "ch-RBC",
      weight: 92,
      type: "publishes",
    },
    {
      source: `topic-${clusterId(1)}`,
      target: "ch-AgencyWire",
      weight: 76,
      type: "publishes",
    },
    {
      source: `topic-${clusterId(1)}`,
      target: "ent-ORG:central-bank",
      weight: 210,
      type: "mentions",
    },
    {
      source: `topic-${clusterId(1)}`,
      target: "ent-PER:governor",
      weight: 128,
      type: "mentions",
    },
    {
      source: `topic-${clusterId(1)}`,
      target: "msg-agency:101",
      weight: 1,
      type: "contains",
    },
  ],
};
