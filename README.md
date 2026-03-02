# Telegram News Pipeline - Data Contracts

Полная спецификация контрактов данных для event-driven конвейера обработки новостей из Telegram.

## 📋 Содержание

- [Обзор](#обзор)
- [Быстрый старт](#быстрый-старт)
- [Архитектура](#архитектура)
- [Документация](#документация)
- [Установка](#установка)
- [Использование](#использование)

## 🎯 Обзор

Проект определяет контракты данных для полного цикла обработки:

1. **Сбор** сырых сообщений из Telegram
2. **Персистентность** в PostgreSQL
3. **Предобработка** текста (очистка, токенизация)
4. **Анализ** sentiment и эмоций
5. **Извлечение** именованных сущностей (NER)
6. **Построение** knowledge graph в Neo4j

### Ключевые особенности

✅ **Event-Driven**: Все взаимодействия через Kafka  
✅ **At-Least-Once Delivery**: С гарантированной идемпотентностью  
✅ **Schema Validation**: JSON Schema для всех событий  
✅ **Replay Support**: Возможность повторной обработки  
✅ **Distributed Tracing**: Сквозная трассировка через `trace_id`  
✅ **Dead Letter Queues**: Обработка ошибок и retry  

## 🚀 Быстрый старт

### Предварительные требования

- Docker & Docker Compose
- PostgreSQL 15+
- Neo4j 5.x
- Apache Kafka 3.x
- Python 3.11+

### Установка

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd Tg_news_project

# 2. Создать .env файл
cp .env.example .env
# Отредактировать .env и заполнить секреты

# 3. Запустить инфраструктуру
docker-compose -f docker-compose.infrastructure.yml up -d

# 4. Применить миграции
chmod +x scripts/*.sh
./scripts/apply_migrations.sh

# 5. Инициализировать Neo4j
./scripts/init_neo4j.sh

# 6. Создать Kafka топики
./scripts/create_kafka_topics.sh

# 7. Валидировать схемы
./scripts/validate_schemas.sh
```

### Проверка

```bash
# Проверить сервисы
docker-compose -f docker-compose.infrastructure.yml ps

# PostgreSQL
psql -h localhost -U postgres -d telegram_news -c "SELECT COUNT(*) FROM schema_migrations;"

# Neo4j
cypher-shell -a bolt://localhost:7687 -u neo4j "SHOW CONSTRAINTS"

# Kafka
kafka-topics.sh --bootstrap-server localhost:9092 --list
```

## 🏗️ Архитектура

### Kafka Topics

```
raw.telegram.messages          → сырые сообщения
  ↓
persisted.messages             → подтверждение записи в БД
  ↓
preprocessed.messages          → обработанный текст
  ↓
  ├─→ sentiment.enriched       → sentiment анализ
  └─→ ner.enriched             → извлечение сущностей
        ↓
      graph.updates            → обновления графа
        ↓
      Neo4j Graph Database
```

### Компоненты

| Компонент | Роль | Input Topic | Output Topic |
|-----------|------|-------------|--------------|
| telegram-collector | Сбор из Telegram | - | raw.telegram.messages |
| message-persister | Запись в Postgres | raw.telegram.messages | persisted.messages |
| preprocessor | Очистка текста | raw.telegram.messages | preprocessed.messages |
| sentiment-analyzer | Анализ sentiment | preprocessed.messages | sentiment.enriched |
| ner-extractor | Извлечение сущностей | preprocessed.messages | ner.enriched |
| graph-builder | Создание графа | sentiment.enriched, ner.enriched | graph.updates |
| neo4j-writer | Запись в Neo4j | graph.updates | - |

### Идемпотентность

**Механизм**: Каждое событие имеет уникальный `event_id = {channel}:{message_id}`

**Проверка дубликатов**:
1. Перед обработкой: проверка в таблице `processed_events`
2. При записи в Postgres: `ON CONFLICT DO NOTHING`
3. При записи в Neo4j: использование `MERGE` вместо `CREATE`

**Пример**:
```python
def process_event(event):
    event_id = event['event_id']
    
    # Проверка дубликата
    if is_already_processed(event_id):
        return
    
    # Обработка в транзакции
    with transaction():
        result = do_processing(event)
        mark_as_processed(event_id)
        commit_kafka_offset()
```

## 📚 Документация

### Основные документы

| Документ | Описание |
|----------|----------|
| [docs/contracts.md](docs/contracts.md) | **Полная спецификация контрактов** |
| [docs/engineering-standards.md](docs/engineering-standards.md) | Стандарты разработки |
| [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md) | Руководство по инфраструктуре |
| [schemas/README.md](schemas/README.md) | Документация JSON Schema |

### JSON Schemas

Все схемы событий в директории `schemas/`:

- `raw_message.schema.json` - Сырое сообщение из Telegram
- `persisted_message.schema.json` - Подтверждение сохранения
- `preprocessed_message.schema.json` - Обработанный текст
- `sentiment_enriched.schema.json` - Результаты sentiment анализа
- `ner_enriched.schema.json` - Извлеченные сущности
- `graph_update.schema.json` - Команды обновления графа

### Примеры

Примеры событий в директории `examples/`:

```bash
examples/
├── raw_message.example.json
├── persisted_message.example.json
├── preprocessed_message.example.json
├── sentiment_enriched.example.json
├── ner_enriched.example.json
└── graph_update.example.json
```

### База данных

**PostgreSQL DDL**: `migrations/001_initial_schema.sql`

Основные таблицы:
- `raw_messages` - Сырые сообщения
- `preprocessed_messages` - Обработанный текст
- `sentiment_results` - Sentiment анализ
- `ner_results` - Именованные сущности
- `entity_relations` - Связи между сущностями
- `processed_events` - Дедупликация
- `outbox` - Transactional Outbox Pattern

**Neo4j Cypher**: `neo4j/init.cypher`

Node Labels:
- `Message` - Сообщение
- `Entity` - Сущность (PERSON, ORG, GPE, LOC, ...)
- `Channel` - Telegram канал
- `Topic` - Тематический кластер

Relationship Types:
- `MENTIONED_IN` - Сущность упоминается в сообщении
- `POSTED_IN` - Сообщение опубликовано в канале
- `RELATES_TO` - Связь между сущностями
- `CO_OCCURS_WITH` - Совместное упоминание

## 🔧 Использование

### Валидация событий

```python
from jsonschema import validate
import json

# Загрузить схему
with open('schemas/raw_message.schema.json') as f:
    schema = json.load(f)

# Создать событие
event = {
    "event_id": "rbc_news:123456",
    "event_type": "raw_message",
    "event_timestamp": "2026-01-31T14:23:45.123Z",
    "event_version": "v1.0.0",
    "source_system": "telegram-collector",
    "trace_id": "550e8400-e29b-41d4-a716-446655440000",
    "payload": { ... }
}

# Валидировать
validate(instance=event, schema=schema)
```

### Отправка в Kafka

```python
from kafka import KafkaProducer
import json
import uuid
from datetime import datetime

producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    key_serializer=lambda k: k.encode('utf-8')
)

event = {
    "event_id": "rbc_news:123456",
    "event_type": "raw_message",
    "event_timestamp": datetime.utcnow().isoformat() + "Z",
    "event_version": "v1.0.0",
    "source_system": "telegram-collector",
    "trace_id": str(uuid.uuid4()),
    "payload": {
        "message_id": 123456,
        "channel": "rbc_news",
        "text": "Центробанк повысил ключевую ставку до 18%",
        "date": "2026-01-31T14:20:00Z",
        "views": 15420,
        "forwards": 234
    }
}

producer.send(
    topic='raw.telegram.messages',
    key=event['event_id'],
    value=event
)
producer.flush()
```

### Чтение из Kafka

```python
from kafka import KafkaConsumer
import json

consumer = KafkaConsumer(
    'raw.telegram.messages',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    key_deserializer=lambda k: k.decode('utf-8'),
    auto_offset_reset='earliest',
    enable_auto_commit=False,
    group_id='my-consumer-group'
)

for message in consumer:
    event = message.value
    event_id = event['event_id']
    
    # Проверка дубликата
    if not is_already_processed(event_id):
        process_event(event)
        mark_as_processed(event_id)
    
    consumer.commit()
```

### Запросы к Neo4j

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)

# Топ-10 упоминаемых сущностей
with driver.session() as session:
    result = session.run("""
        MATCH (e:Entity)
        RETURN e.normalized_name AS name, 
               e.entity_type AS type,
               e.mention_count AS mentions
        ORDER BY e.mention_count DESC
        LIMIT 10
    """)
    
    for record in result:
        print(f"{record['name']} ({record['type']}): {record['mentions']} mentions")
```

## 🛠️ Скрипты

| Скрипт | Описание |
|--------|----------|
| `scripts/create_kafka_topics.sh` | Создать все Kafka топики |
| `scripts/apply_migrations.sh` | Применить миграции PostgreSQL |
| `scripts/init_neo4j.sh` | Инициализировать Neo4j схему |
| `scripts/validate_schemas.sh` | Валидировать JSON схемы |

## 🦆 DuckDB Analytics Layer

Для UI-аналитики добавлен read-only слой DuckDB поверх Parquet lake.
Основная OLTP БД остаётся в Postgres.

### Lake layout

```bash
lake/
├── clean/dt=YYYY-MM-DD/channel=.../*.parquet
├── predictions/topic/dt=.../*.parquet
├── predictions/sentiment/dt=.../*.parquet
├── entities/dt=.../*.parquet
├── clusters/dt=.../window_hours=.../*.parquet
├── ui/final/dt=.../*.parquet
└── _meta/watermarks.json
```

### Ingest Colab outputs в lake

```bash
python analytics_duckdb/ingest.py --colab-outputs-path ./colab_outputs --lake-path ./lake
```

Поддерживаются артефакты:
`telegram_clean.parquet`, `topic_predictions.parquet`, `sentiment_predictions.parquet`,
`doc_entities.parquet`, `clusters.parquet`, `final_table.parquet`.

### Запуск аналитического API

```bash
docker compose -f docker-compose.infrastructure.yml -f analytics_duckdb/docker-compose.yml up --build analytics-duckdb
```

Подробно: `analytics_duckdb/README.md`.

## 🐛 Error Handling

### Dead Letter Queues (DLQ)

Для каждого топика есть соответствующий DLQ:

```
dlq.raw.messages      - Ошибки при первичной обработке
dlq.preprocessing     - Ошибки предобработки
dlq.sentiment         - Ошибки sentiment анализа
dlq.ner              - Ошибки NER
dlq.graph            - Ошибки обновления графа
```

### Retry стратегия

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "initial_delay_ms": 1000,
    "max_delay_ms": 60000,
    "backoff_multiplier": 2
}
```

**Exponential backoff**: 1s → 2s → 4s → DLQ

## 📊 Мониторинг

### Web UIs

- **Neo4j Browser**: http://localhost:7474
- **Kafka UI**: http://localhost:8080
- **Grafana**: http://localhost:3000 (если включен профиль monitoring)

### Метрики

Prometheus метрики для каждого consumer:
- `kafka_messages_processed_total` - Обработано сообщений
- `kafka_messages_failed_total` - Ошибок обработки
- `kafka_messages_dlq_total` - Отправлено в DLQ
- `kafka_message_processing_duration_seconds` - Latency
- `kafka_consumer_lag` - Consumer lag

## 🔐 Безопасность

- Все пароли хранятся в `.env` (не в git)
- Telegram сессии в `.session` файлах (не в git)
- API ключи через environment variables
- PostgreSQL/Neo4j аутентификация
- Kafka без аутентификации (для dev, в prod использовать SASL/SSL)

## 📝 Версионирование

Схемы следуют semantic versioning:

- **v1.0.0** → **v1.1.0**: Добавление опциональных полей (backward compatible)
- **v1.x.x** → **v2.0.0**: Breaking changes (новый топик)

## 🤝 Contributing

При добавлении нового сервиса в pipeline:

1. Определить input/output топики
2. Создать JSON Schema для новых событий
3. Добавить DLQ топик
4. Реализовать идемпотентность
5. Добавить retry логику
6. Добавить метрики
7. Обновить документацию

## 📄 Лицензия

Внутренний проект.

## 📞 Контакты

Вопросы по контрактам данных: <team-email>

---

**Версия**: 1.0.0  
**Последнее обновление**: 2026-01-31
