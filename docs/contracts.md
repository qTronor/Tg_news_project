# Data Pipeline Contracts v1.0

> Multilingual Variant C addendum (2026-04-20): `preprocessed.messages.payload`
> now includes `original_language`, `language_confidence`,
> `is_supported_for_full_analysis`, `analysis_mode`, and `translation_status`.
> `ru`/`en` use full analytics, `other` uses partial mode with multilingual topic
> clustering, and `und` uses unknown safe fallback. See
> `docs/multilingual_processing_variant_c.md`.

**Дата:** 2026-01-31  
**Архитектура:** Event-Driven, At-Least-Once Delivery  
**Идемпотентность:** Обязательна на всех уровнях  
**Replay:** Поддерживается через offset management

---

## 1. Kafka Topics

### Таблица топиков

| Topic Name | Producer | Consumers | Message Key | Partitions | Retention | Schema Version |
|-----------|----------|-----------|-------------|------------|-----------|----------------|
| `raw.telegram.messages` | telegram-collector | message-persister, preprocessor | `{channel}:{message_id}` | 6 | 30d | v1 |
| `persisted.messages` | message-persister | preprocessor, monitoring | `{channel}:{message_id}` | 6 | 7d | v1 |
| `preprocessed.messages` | preprocessor | sentiment-analyzer, ner-extractor | `{channel}:{message_id}` | 6 | 30d | v1 |
| `sentiment.enriched` | sentiment-analyzer | graph-builder, aggregator | `{channel}:{message_id}` | 6 | 30d | v1 |
| `ner.enriched` | ner-extractor | graph-builder, entity-linker | `{channel}:{message_id}` | 6 | 30d | v1 |
| `graph.updates` | graph-builder | neo4j-writer | `{entity_type}:{entity_id}` | 6 | 7d | v1 |
| `dlq.raw.messages` | telegram-collector | manual-review | `{channel}:{message_id}` | 3 | 90d | v1 |
| `dlq.preprocessing` | preprocessor | manual-review | `{channel}:{message_id}` | 3 | 90d | v1 |
| `dlq.sentiment` | sentiment-analyzer | manual-review | `{channel}:{message_id}` | 3 | 90d | v1 |
| `dlq.ner` | ner-extractor | manual-review | `{channel}:{message_id}` | 3 | 90d | v1 |
| `dlq.graph` | graph-builder | manual-review | `{entity_type}:{entity_id}` | 3 | 90d | v1 |

### Naming Convention

- **Основные топики**: `{stage}.{domain}.{entity}`
- **DLQ топики**: `dlq.{stage}`
- **Ключ сообщения**: Гарантирует порядок обработки для одного источника + используется для дедупликации

### Партиционирование

**Стратегия**: По ключу сообщения (channel:message_id)
- Сообщения из одного канала попадают в одну партицию → сохраняется порядок
- 6 партиций = балансировка для 2-6 консьюмеров
- DLQ топики имеют меньше партиций (3) — редко используются

---

## 2. Идемпотентность

### Принципы

1. **Уникальный идентификатор**: `{channel}:{message_id}` — natural key из Telegram
2. **Проверка дубликатов**: При записи в Postgres используется `ON CONFLICT DO NOTHING`
3. **Event Log**: Таблица `processed_events` хранит обработанные event_id
4. **Timestamps**: Каждое событие содержит `event_timestamp` для ordering

### Механизм дедупликации

```python
# Псевдокод для consumer
def process_message(event):
    event_id = f"{event['channel']}:{event['message_id']}"
    
    # Проверка в кэше (Redis) или БД
    if is_already_processed(event_id, event['event_timestamp']):
        log.debug(f"Skipping duplicate event_id={event_id}")
        return
    
    # Обработка в транзакции
    with transaction():
        result = process(event)
        mark_as_processed(event_id, event['event_timestamp'])
        commit_offset(event.offset)
```

### Таблица дедупликации

```sql
CREATE TABLE processed_events (
    event_id VARCHAR(255) PRIMARY KEY,
    event_timestamp TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT NOW(),
    consumer_id VARCHAR(100) NOT NULL,
    INDEX idx_processed_at (processed_at)
);

-- Очистка старых записей (retention 7 дней)
DELETE FROM processed_events WHERE processed_at < NOW() - INTERVAL '7 days';
```

---

## 3. JSON Schema — События

Все схемы находятся в `schemas/*.json`. Основные поля:

### Общие метаданные (все события)

```json
{
  "event_id": "string (format: {channel}:{message_id})",
  "event_type": "enum [raw_message, persisted, preprocessed, sentiment_enriched, ner_enriched, graph_update]",
  "event_timestamp": "string (ISO 8601 UTC)",
  "event_version": "string (semver, например v1.0.0)",
  "source_system": "string (например telegram-collector)",
  "trace_id": "string (UUID для трассировки)"
}
```

### 3.1. raw.telegram.messages

**Schema**: `schemas/raw_message.schema.json`

```json
{
  "event_id": "rbc_news:123456",
  "event_type": "raw_message",
  "event_timestamp": "2026-01-31T14:23:45.123Z",
  "event_version": "v1.0.0",
  "source_system": "telegram-collector",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "message_id": 123456,
    "channel": "rbc_news",
    "text": "Центробанк повысил ключевую ставку до 18%",
    "date": "2026-01-31T14:20:00Z",
    "views": 15420,
    "forwards": 234,
    "reactions": {
      "👍": 45,
      "🔥": 12
    },
    "media": {
      "type": "photo",
      "url": "https://..."
    },
    "edit_date": null,
    "reply_to_message_id": null
  }
}
```

### 3.2. persisted.messages

**Schema**: `schemas/persisted_message.schema.json`

Подтверждение сохранения в Postgres (для мониторинга и триггеров downstream).

```json
{
  "event_id": "rbc_news:123456",
  "event_type": "persisted",
  "event_timestamp": "2026-01-31T14:23:46.500Z",
  "event_version": "v1.0.0",
  "source_system": "message-persister",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "message_id": 123456,
    "channel": "rbc_news",
    "db_id": "uuid-in-postgres",
    "persisted_at": "2026-01-31T14:23:46.500Z",
    "status": "success"
  }
}
```

### 3.3. preprocessed.messages

**Schema**: `schemas/preprocessed_message.schema.json`

После очистки, нормализации текста.

```json
{
  "event_id": "rbc_news:123456",
  "event_type": "preprocessed",
  "event_timestamp": "2026-01-31T14:23:47.200Z",
  "event_version": "v1.0.0",
  "source_system": "preprocessor",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "message_id": 123456,
    "channel": "rbc_news",
    "original_text": "Центробанк повысил ключевую ставку до 18%",
    "cleaned_text": "центробанк повысил ключевую ставку до 18%",
    "normalized_text": "центробанк повысить ключевой ставка до 18%",
    "language": "ru",
    "tokens": ["центробанк", "повысить", "ключевой", "ставка", "18%"],
    "sentences_count": 1,
    "word_count": 6,
    "has_urls": false,
    "has_mentions": false,
    "preprocessing_metadata": {
      "version": "1.0",
      "timestamp": "2026-01-31T14:23:47.200Z"
    }
  }
}
```

### 3.4. sentiment.enriched

**Schema**: `schemas/sentiment_enriched.schema.json`

```json
{
  "event_id": "rbc_news:123456",
  "event_type": "sentiment_enriched",
  "event_timestamp": "2026-01-31T14:23:48.100Z",
  "event_version": "v1.0.0",
  "source_system": "sentiment-analyzer",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "message_id": 123456,
    "channel": "rbc_news",
    "sentiment": {
      "label": "neutral",
      "score": 0.52,
      "positive_prob": 0.15,
      "negative_prob": 0.33,
      "neutral_prob": 0.52
    },
    "emotions": {
      "anger": 0.05,
      "fear": 0.12,
      "joy": 0.08,
      "sadness": 0.10,
      "surprise": 0.15
    },
    "model": {
      "name": "rubert-tiny-sentiment",
      "version": "1.0.2"
    },
    "analyzed_at": "2026-01-31T14:23:48.100Z"
  }
}
```

### 3.5. ner.enriched

**Schema**: `schemas/ner_enriched.schema.json`

```json
{
  "event_id": "rbc_news:123456",
  "event_type": "ner_enriched",
  "event_timestamp": "2026-01-31T14:23:48.500Z",
  "event_version": "v1.0.0",
  "source_system": "ner-extractor",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "message_id": 123456,
    "channel": "rbc_news",
    "entities": [
      {
        "text": "Центробанк",
        "type": "ORG",
        "start": 0,
        "end": 10,
        "confidence": 0.98,
        "normalized": "Центральный банк России",
        "wikidata_id": "Q4198"
      },
      {
        "text": "18%",
        "type": "PERCENT",
        "start": 40,
        "end": 43,
        "confidence": 0.95,
        "normalized": "0.18"
      }
    ],
    "relations": [
      {
        "subject": "Центробанк",
        "predicate": "повысил",
        "object": "ключевую ставку",
        "confidence": 0.85
      }
    ],
    "model": {
      "name": "deeppavlov-ner-ru",
      "version": "0.17.0"
    },
    "extracted_at": "2026-01-31T14:23:48.500Z"
  }
}
```

### 3.6. graph.updates

**Schema**: `schemas/graph_update.schema.json`

Команды для создания/обновления узлов и связей в Neo4j.

```json
{
  "event_id": "ORG:Q4198",
  "event_type": "graph_update",
  "event_timestamp": "2026-01-31T14:23:49.000Z",
  "event_version": "v1.0.0",
  "source_system": "graph-builder",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "operation": "MERGE",
    "entity_type": "ORG",
    "entity_id": "Q4198",
    "properties": {
      "name": "Центральный банк России",
      "aliases": ["ЦБ РФ", "Центробанк"],
      "wikidata_id": "Q4198",
      "first_seen": "2026-01-31T14:23:49.000Z",
      "last_seen": "2026-01-31T14:23:49.000Z",
      "mention_count": 1
    },
    "relationships": [
      {
        "type": "MENTIONED_IN",
        "target_type": "Message",
        "target_id": "rbc_news:123456",
        "properties": {
          "position": 0,
          "context": "повысил ключевую ставку",
          "timestamp": "2026-01-31T14:20:00Z"
        }
      }
    ]
  }
}
```

---

## 4. Postgres Schema (DDL)

### 4.1. raw_messages

Хранение сырых сообщений из Telegram.

```sql
CREATE TABLE raw_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    text TEXT,
    message_date TIMESTAMPTZ NOT NULL,
    views INTEGER DEFAULT 0,
    forwards INTEGER DEFAULT 0,
    reactions JSONB,
    media JSONB,
    edit_date TIMESTAMPTZ,
    reply_to_message_id BIGINT,
    
    -- Метаданные события
    event_id VARCHAR(512) GENERATED ALWAYS AS (channel || ':' || message_id) STORED,
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    
    -- Технические поля
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraints
    UNIQUE (channel, message_id)
);

-- Индексы
CREATE INDEX idx_raw_messages_channel ON raw_messages(channel);
CREATE INDEX idx_raw_messages_date ON raw_messages(message_date DESC);
CREATE INDEX idx_raw_messages_event_timestamp ON raw_messages(event_timestamp DESC);
CREATE INDEX idx_raw_messages_trace_id ON raw_messages(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX idx_raw_messages_text_fts ON raw_messages USING gin(to_tsvector('russian', text));

-- Триггер для updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_raw_messages_updated_at 
    BEFORE UPDATE ON raw_messages 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
```

### 4.2. preprocessed_messages

Результат предобработки текста.

```sql
CREATE TABLE preprocessed_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_message_id UUID NOT NULL REFERENCES raw_messages(id) ON DELETE CASCADE,
    
    -- Идентификаторы
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Обработанный текст
    original_text TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    normalized_text TEXT,
    language VARCHAR(10),
    tokens TEXT[],
    sentences_count INTEGER,
    word_count INTEGER,
    
    -- Флаги
    has_urls BOOLEAN DEFAULT FALSE,
    has_mentions BOOLEAN DEFAULT FALSE,
    
    -- Метаданные
    preprocessing_version VARCHAR(50),
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (channel, message_id)
);

CREATE INDEX idx_preprocessed_messages_raw_id ON preprocessed_messages(raw_message_id);
CREATE INDEX idx_preprocessed_messages_event_id ON preprocessed_messages(event_id);
CREATE INDEX idx_preprocessed_messages_language ON preprocessed_messages(language);
CREATE INDEX idx_preprocessed_messages_normalized_fts ON preprocessed_messages 
    USING gin(to_tsvector('russian', normalized_text));
```

### 4.3. sentiment_results

Результаты sentiment-анализа.

```sql
CREATE TABLE sentiment_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Идентификаторы
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Sentiment
    sentiment_label VARCHAR(50) NOT NULL,
    sentiment_score REAL NOT NULL CHECK (sentiment_score >= 0 AND sentiment_score <= 1),
    positive_prob REAL,
    negative_prob REAL,
    neutral_prob REAL,
    
    -- Emotions
    emotion_anger REAL,
    emotion_fear REAL,
    emotion_joy REAL,
    emotion_sadness REAL,
    emotion_surprise REAL,
    
    -- Модель
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    
    -- Метаданные
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE (channel, message_id)
);

CREATE INDEX idx_sentiment_results_preprocessed_id ON sentiment_results(preprocessed_message_id);
CREATE INDEX idx_sentiment_results_event_id ON sentiment_results(event_id);
CREATE INDEX idx_sentiment_results_label ON sentiment_results(sentiment_label);
CREATE INDEX idx_sentiment_results_score ON sentiment_results(sentiment_score DESC);
```

### 4.4. ner_results

Извлеченные сущности (Named Entity Recognition).

```sql
CREATE TABLE ner_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Идентификаторы
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    event_id VARCHAR(512) NOT NULL,
    
    -- Entity
    entity_text VARCHAR(500) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    start_pos INTEGER NOT NULL,
    end_pos INTEGER NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    normalized_text VARCHAR(500),
    wikidata_id VARCHAR(50),
    
    -- Модель
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    
    -- Метаданные
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ner_results_preprocessed_id ON ner_results(preprocessed_message_id);
CREATE INDEX idx_ner_results_event_id ON ner_results(event_id);
CREATE INDEX idx_ner_results_entity_type ON ner_results(entity_type);
CREATE INDEX idx_ner_results_entity_text ON ner_results(entity_text);
CREATE INDEX idx_ner_results_wikidata ON ner_results(wikidata_id) WHERE wikidata_id IS NOT NULL;
```

### 4.5. entity_relations

Связи между сущностями (тройки SPO).

```sql
CREATE TABLE entity_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preprocessed_message_id UUID NOT NULL REFERENCES preprocessed_messages(id) ON DELETE CASCADE,
    
    -- Идентификаторы
    message_id BIGINT NOT NULL,
    channel VARCHAR(255) NOT NULL,
    
    -- Relation
    subject VARCHAR(500) NOT NULL,
    predicate VARCHAR(200) NOT NULL,
    object VARCHAR(500) NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    
    -- Метаданные
    event_timestamp TIMESTAMPTZ NOT NULL,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_entity_relations_preprocessed_id ON entity_relations(preprocessed_message_id);
CREATE INDEX idx_entity_relations_subject ON entity_relations(subject);
CREATE INDEX idx_entity_relations_predicate ON entity_relations(predicate);
CREATE INDEX idx_entity_relations_object ON entity_relations(object);
```

### 4.6. processed_events (дедупликация)

Отслеживание обработанных событий для идемпотентности.

```sql
CREATE TABLE processed_events (
    event_id VARCHAR(512) PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    consumer_id VARCHAR(100) NOT NULL,
    processing_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_completed_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'processing',
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_processed_events_consumer ON processed_events(consumer_id);
CREATE INDEX idx_processed_events_type ON processed_events(event_type);
CREATE INDEX idx_processed_events_timestamp ON processed_events(event_timestamp DESC);
CREATE INDEX idx_processed_events_status ON processed_events(status);
CREATE INDEX idx_processed_events_created ON processed_events(created_at);

-- Cleanup старых записей (retention policy)
-- Запускать через cron или pg_cron
CREATE OR REPLACE FUNCTION cleanup_processed_events()
RETURNS void AS $$
BEGIN
    DELETE FROM processed_events 
    WHERE created_at < NOW() - INTERVAL '7 days' 
    AND status = 'completed';
END;
$$ LANGUAGE plpgsql;
```

### 4.7. outbox (Transactional Outbox Pattern)

Для гарантированной доставки событий в Kafka.

```sql
CREATE TABLE outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(512) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    
    -- Kafka metadata
    topic VARCHAR(255) NOT NULL,
    message_key VARCHAR(512) NOT NULL,
    partition_key VARCHAR(512),
    
    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    
    -- Ordering
    sequence_number BIGSERIAL
);

CREATE INDEX idx_outbox_status ON outbox(status, created_at) WHERE status = 'pending';
CREATE INDEX idx_outbox_aggregate ON outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_outbox_sequence ON outbox(sequence_number);
CREATE INDEX idx_outbox_topic ON outbox(topic);

-- Cleanup успешно отправленных (retention 1 день)
CREATE OR REPLACE FUNCTION cleanup_outbox()
RETURNS void AS $$
BEGIN
    DELETE FROM outbox 
    WHERE status = 'published' 
    AND published_at < NOW() - INTERVAL '1 day';
END;
$$ LANGUAGE plpgsql;
```

---

## 5. Neo4j Graph Model

### 5.1. Node Labels

#### Message
Узел сообщения из Telegram.

```cypher
CREATE CONSTRAINT message_event_id IF NOT EXISTS
FOR (m:Message) REQUIRE m.event_id IS UNIQUE;

CREATE INDEX message_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.timestamp);

CREATE INDEX message_channel IF NOT EXISTS
FOR (m:Message) ON (m.channel);

-- Свойства
{
  event_id: "rbc_news:123456",
  message_id: 123456,
  channel: "rbc_news",
  text: "...",
  cleaned_text: "...",
  timestamp: datetime("2026-01-31T14:20:00Z"),
  views: 15420,
  forwards: 234,
  sentiment_label: "neutral",
  sentiment_score: 0.52,
  created_at: datetime()
}
```

#### Entity
Извлеченная сущность (PERSON, ORG, LOC, etc).

```cypher
CREATE CONSTRAINT entity_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

CREATE INDEX entity_type IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_name IF NOT EXISTS
FOR (e:Entity) ON (e.normalized_name);

-- Свойства
{
  entity_id: "ORG:Q4198",
  entity_type: "ORG",
  original_text: "Центробанк",
  normalized_name: "Центральный банк России",
  wikidata_id: "Q4198",
  aliases: ["ЦБ РФ", "Центробанк"],
  first_seen: datetime(),
  last_seen: datetime(),
  mention_count: 42,
  avg_sentiment: 0.48
}
```

#### Channel
Telegram канал.

```cypher
CREATE CONSTRAINT channel_name IF NOT EXISTS
FOR (c:Channel) REQUIRE c.name IS UNIQUE;

-- Свойства
{
  name: "rbc_news",
  title: "РБК Новости",
  description: "...",
  subscriber_count: 500000,
  message_count: 12543,
  first_message_date: datetime(),
  last_message_date: datetime(),
  avg_sentiment: 0.51
}
```

#### Topic
Тематический кластер (для будущего topic modeling).

```cypher
CREATE CONSTRAINT topic_id IF NOT EXISTS
FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE;

-- Свойства
{
  topic_id: "topic_15",
  label: "Экономика и финансы",
  keywords: ["ставка", "инфляция", "центробанк", "рубль"],
  message_count: 234,
  first_seen: datetime(),
  last_seen: datetime()
}
```

### 5.2. Relationship Types

#### POSTED_IN
Message → Channel

```cypher
// Свойства
{
  timestamp: datetime("2026-01-31T14:20:00Z")
}
```

#### MENTIONS
Message → Entity

```cypher
// Свойства
{
  position: 0,
  context: "повысил ключевую ставку",
  confidence: 0.98,
  sentiment: 0.52
}
```

#### RELATES_TO
Entity → Entity (связь через subject-predicate-object)

```cypher
// Свойства
{
  predicate: "повысил",
  source_message: "rbc_news:123456",
  timestamp: datetime(),
  confidence: 0.85
}
```

#### CO_OCCURS_WITH
Entity → Entity (упоминаются в одном сообщении)

```cypher
// Свойства
{
  count: 15,
  first_occurrence: datetime(),
  last_occurrence: datetime(),
  avg_distance: 5.3  // среднее расстояние в токенах
}
```

#### REPLIES_TO
Message → Message

```cypher
// Свойства
{
  timestamp: datetime()
}
```

#### BELONGS_TO_TOPIC
Message → Topic

```cypher
// Свойства
{
  probability: 0.87,
  assigned_at: datetime()
}
```

### 5.3. Constraints & Indexes

```cypher
// Constraints (уникальность)
CREATE CONSTRAINT message_event_id IF NOT EXISTS
FOR (m:Message) REQUIRE m.event_id IS UNIQUE;

CREATE CONSTRAINT entity_id IF NOT EXISTS
FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

CREATE CONSTRAINT channel_name IF NOT EXISTS
FOR (c:Channel) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT topic_id IF NOT EXISTS
FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE;

// Indexes (производительность)
CREATE INDEX message_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.timestamp);

CREATE INDEX message_channel IF NOT EXISTS
FOR (m:Message) ON (m.channel);

CREATE INDEX message_sentiment IF NOT EXISTS
FOR (m:Message) ON (m.sentiment_label);

CREATE INDEX entity_type IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type);

CREATE INDEX entity_normalized_name IF NOT EXISTS
FOR (e:Entity) ON (e.normalized_name);

CREATE INDEX entity_mention_count IF NOT EXISTS
FOR (e:Entity) ON (e.mention_count);

// Composite indexes
CREATE INDEX message_channel_timestamp IF NOT EXISTS
FOR (m:Message) ON (m.channel, m.timestamp);

CREATE INDEX entity_type_name IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type, e.normalized_name);
```

### 5.4. Типовые запросы для UI

#### 1. Топ упоминаемых сущностей за период

```cypher
// Топ-20 сущностей по количеству упоминаний за последние 7 дней
MATCH (m:Message)-[r:MENTIONS]->(e:Entity)
WHERE m.timestamp >= datetime() - duration('P7D')
WITH e, COUNT(DISTINCT m) AS mention_count, AVG(m.sentiment_score) AS avg_sentiment
RETURN 
    e.entity_type AS type,
    e.normalized_name AS name,
    mention_count,
    avg_sentiment,
    e.wikidata_id AS wikidata_id
ORDER BY mention_count DESC
LIMIT 20;
```

#### 2. Временная динамика sentiment для канала

```cypher
// Агрегация sentiment по дням для канала
MATCH (m:Message)-[:POSTED_IN]->(c:Channel {name: $channel_name})
WHERE m.timestamp >= datetime() - duration('P30D')
WITH date(m.timestamp) AS day, 
     AVG(m.sentiment_score) AS avg_sentiment,
     COUNT(m) AS message_count
RETURN 
    day,
    avg_sentiment,
    message_count
ORDER BY day ASC;
```

#### 3. Граф связей между сущностями

```cypher
// Найти связанные сущности для заданной (например, "Центробанк")
MATCH path = (e1:Entity {normalized_name: $entity_name})-[r:RELATES_TO|CO_OCCURS_WITH*1..2]-(e2:Entity)
WHERE e1 <> e2
WITH e2, 
     COUNT(DISTINCT r) AS connection_strength,
     MIN([rel IN relationships(path) | rel.confidence]) AS min_confidence
WHERE connection_strength >= 3
RETURN 
    e2.entity_type AS type,
    e2.normalized_name AS name,
    connection_strength,
    min_confidence,
    e2.mention_count AS total_mentions
ORDER BY connection_strength DESC
LIMIT 50;
```

#### 4. Сообщения с высоким engagement по сущности

```cypher
// Топ сообщений, упоминающих сущность, по views+forwards
MATCH (e:Entity {normalized_name: $entity_name})<-[:MENTIONS]-(m:Message)
WITH m, (m.views + m.forwards * 10) AS engagement_score
RETURN 
    m.event_id AS event_id,
    m.channel AS channel,
    m.text AS text,
    m.timestamp AS timestamp,
    m.views AS views,
    m.forwards AS forwards,
    m.sentiment_label AS sentiment,
    engagement_score
ORDER BY engagement_score DESC
LIMIT 20;
```

#### 5. Co-occurrence матрица для entity pairs

```cypher
// Часто упоминаемые вместе сущности (для построения heatmap/network)
MATCH (e1:Entity)<-[:MENTIONS]-(m:Message)-[:MENTIONS]->(e2:Entity)
WHERE e1.entity_id < e2.entity_id  // Избегаем дубликатов
    AND e1.entity_type IN ['ORG', 'PERSON', 'GPE']
    AND e2.entity_type IN ['ORG', 'PERSON', 'GPE']
    AND m.timestamp >= datetime() - duration('P7D')
WITH e1, e2, COUNT(DISTINCT m) AS co_occurrence_count
WHERE co_occurrence_count >= 5
RETURN 
    e1.normalized_name AS entity1,
    e2.normalized_name AS entity2,
    co_occurrence_count,
    e1.entity_type AS type1,
    e2.entity_type AS type2
ORDER BY co_occurrence_count DESC
LIMIT 100;
```

---

## 6. Error Handling: DLQ, Retries, Monitoring

### 6.1. Retry Strategy

**Принцип**: Exponential backoff с максимальным числом попыток.

```python
# Конфигурация для consumer
RETRY_CONFIG = {
    "max_retries": 3,
    "initial_delay_ms": 1000,
    "max_delay_ms": 60000,
    "backoff_multiplier": 2,
    "jitter": True
}

def calculate_retry_delay(retry_count: int) -> int:
    delay = min(
        RETRY_CONFIG["initial_delay_ms"] * (RETRY_CONFIG["backoff_multiplier"] ** retry_count),
        RETRY_CONFIG["max_delay_ms"]
    )
    if RETRY_CONFIG["jitter"]:
        delay = delay * (0.5 + random.random() * 0.5)
    return int(delay)
```

### 6.2. Dead Letter Queue (DLQ)

**Когда отправлять в DLQ**:
1. Превышено `max_retries`
2. Validation error (некорректная схема)
3. Business logic error (не transient)
4. Poison message (вызывает crash consumer)

**Формат DLQ сообщения**:

```json
{
  "original_topic": "raw.telegram.messages",
  "original_partition": 3,
  "original_offset": 12345,
  "original_key": "rbc_news:123456",
  "original_value": { ... },
  "original_headers": { ... },
  "error_info": {
    "error_type": "ValidationError",
    "error_message": "Missing required field 'message_id'",
    "error_stacktrace": "...",
    "retry_count": 3,
    "first_attempt_timestamp": "2026-01-31T14:23:45.123Z",
    "last_attempt_timestamp": "2026-01-31T14:25:12.456Z",
    "consumer_id": "preprocessor-instance-01"
  },
  "dlq_timestamp": "2026-01-31T14:25:12.500Z"
}
```

### 6.3. Consumer Error Handling Pattern

```python
from kafka import KafkaConsumer, KafkaProducer
import json
import logging
import time

log = logging.getLogger(__name__)

class ResilientConsumer:
    def __init__(self, topic: str, dlq_topic: str, processor_func):
        self.consumer = KafkaConsumer(topic, ...)
        self.producer = KafkaProducer(...)
        self.dlq_topic = dlq_topic
        self.processor_func = processor_func
    
    def process_with_retry(self, message):
        event_id = message.key.decode('utf-8')
        retry_count = 0
        
        while retry_count <= RETRY_CONFIG["max_retries"]:
            try:
                # Проверка дедупликации
                if self._is_already_processed(event_id):
                    log.info(f"Skipping duplicate event_id={event_id}")
                    return True
                
                # Обработка
                result = self.processor_func(message.value)
                
                # Отметка как обработанного
                self._mark_as_processed(event_id)
                
                return True
                
            except ValidationError as e:
                # Не ретраить — сразу в DLQ
                log.error(f"Validation error for event_id={event_id}: {e}")
                self._send_to_dlq(message, e, retry_count)
                return False
                
            except TransientError as e:
                # Ретраить
                retry_count += 1
                if retry_count > RETRY_CONFIG["max_retries"]:
                    log.error(f"Max retries exceeded for event_id={event_id}")
                    self._send_to_dlq(message, e, retry_count)
                    return False
                
                delay = calculate_retry_delay(retry_count)
                log.warning(f"Retry {retry_count}/{RETRY_CONFIG['max_retries']} "
                           f"for event_id={event_id} after {delay}ms: {e}")
                time.sleep(delay / 1000)
                
            except Exception as e:
                # Неожиданная ошибка — логируем и в DLQ
                log.exception(f"Unexpected error for event_id={event_id}")
                self._send_to_dlq(message, e, retry_count)
                return False
    
    def _send_to_dlq(self, message, error, retry_count):
        dlq_payload = {
            "original_topic": message.topic,
            "original_partition": message.partition,
            "original_offset": message.offset,
            "original_key": message.key.decode('utf-8'),
            "original_value": json.loads(message.value),
            "original_headers": dict(message.headers),
            "error_info": {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "retry_count": retry_count,
                "consumer_id": self.consumer_id
            },
            "dlq_timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        self.producer.send(
            self.dlq_topic,
            key=message.key,
            value=json.dumps(dlq_payload).encode('utf-8')
        )
```

### 6.4. Мониторинг и алерты

**Метрики для Prometheus**:

```python
from prometheus_client import Counter, Histogram, Gauge

# Счетчики обработанных сообщений
messages_processed = Counter(
    'kafka_messages_processed_total',
    'Total messages processed',
    ['topic', 'consumer_group', 'status']
)

# Ошибки
messages_failed = Counter(
    'kafka_messages_failed_total',
    'Total messages failed',
    ['topic', 'consumer_group', 'error_type']
)

# DLQ
messages_dlq = Counter(
    'kafka_messages_dlq_total',
    'Total messages sent to DLQ',
    ['topic', 'consumer_group']
)

# Latency обработки
processing_duration = Histogram(
    'kafka_message_processing_duration_seconds',
    'Message processing duration',
    ['topic', 'consumer_group']
)

# Consumer lag
consumer_lag = Gauge(
    'kafka_consumer_lag',
    'Consumer lag per partition',
    ['topic', 'consumer_group', 'partition']
)
```

**Алерты**:

1. **High Consumer Lag**: Lag > 10000 сообщений
2. **DLQ Rate**: DLQ rate > 5% от обработанных
3. **Processing Errors**: Error rate > 10%
4. **Slow Processing**: P99 latency > 5 секунд
5. **Consumer Down**: Нет heartbeat > 2 минуты

---

## 7. Versioning и Schema Evolution

### 7.1. Принципы

1. **Backward Compatibility**: Новые версии schema должны читать старые события
2. **Forward Compatibility**: Старые версии consumer должны игнорировать новые поля
3. **Schema Registry**: Использовать Confluent Schema Registry или Apicurio
4. **Semver**: `v1.0.0`, `v1.1.0` (minor — добавление полей), `v2.0.0` (major — breaking change)

### 7.2. Стратегия миграции

**При добавлении нового поля** (v1.0.0 → v1.1.0):
- Поле опциональное с default значением
- Старые consumers игнорируют новое поле
- Новые consumers обрабатывают оба варианта

**При breaking change** (v1.x.x → v2.0.0):
- Создать новый топик: `raw.telegram.messages.v2`
- Запустить оба producer параллельно (dual-write)
- Постепенно мигрировать consumers на v2
- Через N дней отключить v1 топик

### 7.3. Schema Validation

```python
from jsonschema import validate, ValidationError
import json

def load_schema(version: str) -> dict:
    with open(f"schemas/raw_message.schema.{version}.json") as f:
        return json.load(f)

def validate_event(event: dict, schema_version: str = "v1.0.0"):
    schema = load_schema(schema_version)
    try:
        validate(instance=event, schema=schema)
        return True
    except ValidationError as e:
        log.error(f"Schema validation failed: {e.message}")
        return False
```

---

## 8. Checklist для добавления нового сервиса

При добавлении нового consumer в pipeline:

- [ ] Определить input/output топики
- [ ] Создать JSON Schema для новых событий (если нужно)
- [ ] Добавить DLQ топик в Kafka
- [ ] Реализовать идемпотентность (проверка `processed_events`)
- [ ] Добавить retry с exponential backoff
- [ ] Обработать DLQ случаи
- [ ] Добавить метрики (Prometheus)
- [ ] Добавить трассировку (передавать `trace_id`)
- [ ] Добавить healthcheck endpoint
- [ ] Создать Postgres таблицы (если нужно)
- [ ] Обновить Neo4j Cypher queries (если добавляется граф)
- [ ] Написать integration тесты
- [ ] Документировать в `docs/services/<service_name>.md`

---

## 9. Ссылки

- **JSON Schemas**: `schemas/*.json`
- **Postgres Migrations**: `migrations/*.sql` (создать)
- **Neo4j Init Script**: `neo4j/init.cypher` (создать)
- **Kafka Config**: `kafka/topics.yml` (создать)
- **Engineering Standards**: `docs/engineering-standards.md`

---

**Версия документа**: 1.0.0  
**Последнее обновление**: 2026-01-31  
**Автор**: System Architect
