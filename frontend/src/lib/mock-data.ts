import type {
  OverviewStats,
  Topic,
  TopicDetail,
  Message,
  Entity,
  SentimentPoint,
  GraphData,
} from "@/types";

const NOW = new Date();
function hoursAgo(h: number) {
  return new Date(NOW.getTime() - h * 3600_000).toISOString();
}

export const mockOverview: OverviewStats = {
  total_messages: 12847,
  messages_change_pct: 14.3,
  new_topics: 7,
  topics_change: 3,
  active_channels: 42,
  avg_sentiment: -0.08,
};

const channels = ["РБК", "ТАСС", "Коммерсантъ", "Медуза", "Интерфакс", "Ведомости", "RT", "Известия", "Газета.ру", "РИА Новости"];

function makeMsgs(topic: string, clusterId: number, count: number): Message[] {
  const texts: Record<string, string[]> = {
    "Ставка ЦБ": [
      "ЦБ повысил ключевую ставку до 21% годовых. Набиуллина заявила о необходимости сдерживания инфляции.",
      "Рынок отреагировал падением после решения Центробанка по ставке. Аналитики ожидали повышение лишь до 20%.",
      "Набиуллина: «Инфляционные ожидания остаются на повышенном уровне, мы вынуждены действовать решительно».",
      "Эксперты прогнозируют замедление ипотечного кредитования после очередного повышения ключевой ставки.",
      "Минфин: повышение ставки ЦБ не повлияет на планы по размещению ОФЗ в текущем квартале.",
    ],
    "Выборы в Германии": [
      "На выборах в бундестаг лидирует ХДС/ХСС. Шольц признал поражение СДПГ.",
      "Новый канцлер Германии обещает пересмотр энергетической политики и отношений с Россией.",
      "Результаты выборов в Германии могут повлиять на санкционную политику ЕС.",
      "АдГ получила рекордное количество мест в бундестаге, эксперты говорят о росте правого популизма.",
    ],
    "Нефть ОПЕК+": [
      "Страны ОПЕК+ договорились о сокращении добычи нефти на 1 млн баррелей в сутки.",
      "Цена нефти Brent превысила $85 за баррель на фоне решения ОПЕК+.",
      "Аналитики Goldman Sachs повысили прогноз цены на нефть до $90 к концу года.",
    ],
    "ИИ-регулирование": [
      "ЕС утвердил AI Act — первый в мире всеобъемлющий закон о регулировании ИИ.",
      "OpenAI и Google выступили с совместным заявлением о необходимости саморегулирования отрасли ИИ.",
      "Россия разрабатывает собственный закон о регулировании генеративного ИИ по аналогии с AI Act.",
    ],
    "Криптовалюты": [
      "Bitcoin обновил исторический максимум, преодолев отметку $100,000.",
      "SEC одобрила ETF на Ethereum, рынок отреагировал ростом на 15%.",
      "Центробанки БРИКС обсуждают создание единой платформы для расчетов в цифровых валютах.",
    ],
    "Климат COP": [
      "На COP30 достигнуто историческое соглашение о финансировании климатических потерь развивающихся стран.",
      "Россия взяла на себя обязательство достичь углеродной нейтральности к 2060 году.",
    ],
  };
  const topicTexts = texts[topic] || [`Сообщение по теме "${topic}".`];
  return Array.from({ length: count }, (_, i) => ({
    event_id: `${channels[i % channels.length].toLowerCase()}:${10000 + clusterId * 100 + i}`,
    channel: channels[i % channels.length],
    message_id: 10000 + clusterId * 100 + i,
    text: topicTexts[i % topicTexts.length],
    date: hoursAgo(Math.random() * 24),
    views: Math.floor(Math.random() * 50000) + 1000,
    forwards: Math.floor(Math.random() * 2000) + 50,
    topic_label: topic,
    cluster_id: clusterId,
    sentiment_score: (Math.random() - 0.5) * 2,
    sentiment_label: undefined,
    entities: [
      { id: `e-${i}-1`, text: topic.split(" ")[0], type: "ORG" as const, mention_count: Math.floor(Math.random() * 500) },
    ],
  }));
}

export const mockTopics: Topic[] = [
  {
    cluster_id: 1, label: "Ставка ЦБ", message_count: 342, channel_count: 12,
    avg_sentiment: -0.42, is_new: true, first_seen: hoursAgo(8), last_seen: hoursAgo(0.5),
    top_entities: [
      { id: "e1", text: "ЦБ РФ", type: "ORG", mention_count: 287 },
      { id: "e2", text: "Набиуллина", type: "PER", mention_count: 198 },
      { id: "e3", text: "Москва", type: "LOC", mention_count: 87 },
    ],
    top_keywords: ["ставка", "ЦБ", "инфляция", "процент", "рефинансирование"],
    sparkline: [2, 5, 12, 28, 45, 62, 54, 41, 33, 27, 19, 14],
    channels: channels.slice(0, 12).map(c => ({ channel: c, count: Math.floor(Math.random() * 60) + 5 })),
  },
  {
    cluster_id: 2, label: "Выборы в Германии", message_count: 198, channel_count: 8,
    avg_sentiment: 0.12, is_new: false, first_seen: hoursAgo(48), last_seen: hoursAgo(1),
    top_entities: [
      { id: "e4", text: "Шольц", type: "PER", mention_count: 134 },
      { id: "e5", text: "НАТО", type: "ORG", mention_count: 89 },
      { id: "e6", text: "Берлин", type: "LOC", mention_count: 76 },
    ],
    top_keywords: ["бундестаг", "ХДС", "выборы", "канцлер", "Германия"],
    sparkline: [15, 22, 34, 28, 18, 12, 9, 8, 11, 14, 15, 12],
    channels: channels.slice(0, 8).map(c => ({ channel: c, count: Math.floor(Math.random() * 40) + 3 })),
  },
  {
    cluster_id: 3, label: "Нефть ОПЕК+", message_count: 156, channel_count: 11,
    avg_sentiment: -0.10, is_new: false, first_seen: hoursAgo(72), last_seen: hoursAgo(2),
    top_entities: [
      { id: "e7", text: "ОПЕК", type: "ORG", mention_count: 145 },
      { id: "e8", text: "Саудовская Аравия", type: "LOC", mention_count: 67 },
    ],
    top_keywords: ["нефть", "баррель", "добыча", "ОПЕК+", "Brent"],
    sparkline: [8, 10, 12, 11, 14, 18, 22, 19, 16, 13, 11, 12],
    channels: channels.slice(0, 11).map(c => ({ channel: c, count: Math.floor(Math.random() * 30) + 2 })),
  },
  {
    cluster_id: 4, label: "ИИ-регулирование", message_count: 134, channel_count: 9,
    avg_sentiment: 0.24, is_new: true, first_seen: hoursAgo(12), last_seen: hoursAgo(0.2),
    top_entities: [
      { id: "e9", text: "OpenAI", type: "ORG", mention_count: 98 },
      { id: "e10", text: "ЕС", type: "ORG", mention_count: 87 },
    ],
    top_keywords: ["AI Act", "ИИ", "регулирование", "нейросети", "GPT"],
    sparkline: [0, 0, 2, 5, 12, 28, 34, 22, 15, 10, 6, 0],
    channels: channels.slice(0, 9).map(c => ({ channel: c, count: Math.floor(Math.random() * 25) + 1 })),
  },
  {
    cluster_id: 5, label: "Криптовалюты", message_count: 112, channel_count: 7,
    avg_sentiment: 0.56, is_new: false, first_seen: hoursAgo(96), last_seen: hoursAgo(3),
    top_entities: [
      { id: "e11", text: "Bitcoin", type: "MISC", mention_count: 89 },
      { id: "e12", text: "SEC", type: "ORG", mention_count: 54 },
    ],
    top_keywords: ["bitcoin", "ETF", "крипто", "Ethereum", "блокчейн"],
    sparkline: [4, 6, 8, 12, 15, 11, 8, 10, 14, 18, 12, 6],
    channels: channels.slice(0, 7).map(c => ({ channel: c, count: Math.floor(Math.random() * 20) + 1 })),
  },
  {
    cluster_id: 6, label: "Климат COP30", message_count: 78, channel_count: 6,
    avg_sentiment: 0.18, is_new: true, first_seen: hoursAgo(6), last_seen: hoursAgo(1),
    top_entities: [
      { id: "e13", text: "ООН", type: "ORG", mention_count: 65 },
      { id: "e14", text: "Бразилия", type: "LOC", mention_count: 42 },
    ],
    top_keywords: ["COP30", "климат", "углерод", "выбросы", "нейтральность"],
    sparkline: [0, 0, 0, 3, 8, 15, 22, 18, 12, 0, 0, 0],
    channels: channels.slice(0, 6).map(c => ({ channel: c, count: Math.floor(Math.random() * 15) + 1 })),
  },
];

export function mockTopicDetail(clusterId: number): TopicDetail {
  const topic = mockTopics.find(t => t.cluster_id === clusterId) || mockTopics[0];
  const s = topic.avg_sentiment;
  return {
    ...topic,
    representative_messages: makeMsgs(topic.label, topic.cluster_id, 5),
    related_topics: mockTopics
      .filter(t => t.cluster_id !== clusterId)
      .slice(0, 3)
      .map(t => ({ cluster_id: t.cluster_id, label: t.label, similarity: +(Math.random() * 0.5 + 0.4).toFixed(2) })),
    sentiment_breakdown: {
      positive: s > 0 ? 40 + Math.random() * 20 : 10 + Math.random() * 15,
      neutral: 20 + Math.random() * 20,
      negative: s < 0 ? 40 + Math.random() * 20 : 10 + Math.random() * 15,
    },
    volume_timeline: Array.from({ length: 24 }, (_, i) => ({
      time: hoursAgo(24 - i),
      count: Math.floor(Math.random() * (topic.message_count / 8)) + 1,
    })),
  };
}

export const mockEntities: Entity[] = [
  { id: "e1", text: "ЦБ РФ", type: "ORG", normalized: "Центральный банк РФ", mention_count: 1247, topic_count: 5, channel_count: 23, trend_pct: 34 },
  { id: "e2", text: "Путин В.В.", type: "PER", normalized: "Путин Владимир Владимирович", mention_count: 987, topic_count: 8, channel_count: 31, trend_pct: 0 },
  { id: "e3", text: "Москва", type: "LOC", mention_count: 845, topic_count: 12, channel_count: 28, trend_pct: -12 },
  { id: "e4", text: "Набиуллина", type: "PER", normalized: "Набиуллина Эльвира Сахипзадовна", mention_count: 543, topic_count: 3, channel_count: 18, trend_pct: 67 },
  { id: "e5", text: "ОПЕК", type: "ORG", mention_count: 456, topic_count: 2, channel_count: 15, trend_pct: 8 },
  { id: "e6", text: "ЕС", type: "ORG", normalized: "Европейский союз", mention_count: 412, topic_count: 4, channel_count: 22, trend_pct: -5 },
  { id: "e7", text: "Шольц", type: "PER", normalized: "Шольц Олаф", mention_count: 378, topic_count: 2, channel_count: 12, trend_pct: -28 },
  { id: "e8", text: "OpenAI", type: "ORG", mention_count: 312, topic_count: 2, channel_count: 14, trend_pct: 45 },
  { id: "e9", text: "Bitcoin", type: "MISC", mention_count: 289, topic_count: 1, channel_count: 11, trend_pct: 22 },
  { id: "e10", text: "Берлин", type: "LOC", mention_count: 234, topic_count: 3, channel_count: 10, trend_pct: -15 },
  { id: "e11", text: "SEC", type: "ORG", mention_count: 198, topic_count: 2, channel_count: 8, trend_pct: 18 },
  { id: "e12", text: "ООН", type: "ORG", mention_count: 187, topic_count: 3, channel_count: 16, trend_pct: 5 },
];

export const mockSentiment: SentimentPoint[] = Array.from({ length: 24 }, (_, i) => ({
  time: hoursAgo(24 - i),
  positive: Math.floor(Math.random() * 200 + 100),
  neutral: Math.floor(Math.random() * 300 + 200),
  negative: Math.floor(Math.random() * 150 + 80),
}));

export const mockMessages: Message[] = mockTopics.flatMap(t =>
  makeMsgs(t.label, t.cluster_id, 8)
).sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

export const mockGraph: GraphData = {
  nodes: [
    ...mockTopics.map(t => ({ id: `topic-${t.cluster_id}`, label: t.label, type: "topic" as const, weight: t.message_count, community: t.cluster_id })),
    ...channels.map((c, i) => ({ id: `ch-${i}`, label: c, type: "channel" as const, weight: Math.floor(Math.random() * 200 + 50), community: i % 3 })),
    ...mockEntities.slice(0, 8).map(e => ({
      id: `ent-${e.id}`,
      label: e.text,
      type: `entity_${e.type.toLowerCase()}` as GraphData["nodes"][0]["type"],
      weight: e.mention_count || 100,
      community: Math.floor(Math.random() * 4),
    })),
  ],
  edges: [
    ...mockTopics.flatMap(t =>
      t.channels.slice(0, 4).map((c, ci) => ({
        source: `topic-${t.cluster_id}`,
        target: `ch-${channels.indexOf(c.channel)}`,
        weight: c.count,
        type: "publishes",
      }))
    ),
    ...mockTopics.flatMap(t =>
      t.top_entities.slice(0, 2).map(e => ({
        source: `topic-${t.cluster_id}`,
        target: `ent-${e.id}`,
        weight: e.mention_count || 50,
        type: "mentions",
      }))
    ),
    { source: "ent-e1", target: "ent-e2", weight: 120, type: "co_mentioned" },
    { source: "ent-e4", target: "ent-e1", weight: 95, type: "co_mentioned" },
    { source: "ent-e5", target: "ent-e8", weight: 40, type: "co_mentioned" },
  ],
};
