# Реализация системы Telegram News Pipeline

Документ описывает реализацию системы в целевом виде: все контуры, сервисы и технологии считаются развернутыми и работающими в единой платформе потокового анализа.

PlantUML-диаграмма последовательности: [`implementation_sequence.puml`](./implementation_sequence.puml)
Концептуальная (high-level) последовательность: [`implementation_sequence_conceptual.puml`](./implementation_sequence_conceptual.puml)
Компонентная обзорная (updated): [`architecture_overview_updated.puml`](./architecture_overview_updated.puml)

## 1. Архитектурная модель реализации

Система реализована как событийно-ориентированная микросервисная платформа с четырьмя основными уровнями:

- клиентский слой;
- платформа обработки;
- платформенные ресурсы;
- внешние интерфейсы взаимодействия.

Внутри платформы обработки выделены контуры:

- контур сбора и подготовки данных;
- контур аналитики AI/NLP;
- контур тематической кластеризации и детекции новизны;
- контур графовой аналитики;
- контур дообучения и жизненного цикла моделей;
- контур API и управления доступом.

## 2. Технологический стек

### 2.1 Серверный и событийный контур

- Python 3.11+;
- Apache Kafka + Zookeeper (транспорт событий и буферизация потока);
- aiokafka (producer/consumer);
- asyncpg + SQLAlchemy (асинхронный доступ к PostgreSQL);
- Pydantic (контракты и конфигурации);
- JSON Schema (валидация событий);
- DLQ-топики для обработки ошибок.

### 2.2 Аналитика и ML/NLP

- transformers + RuBERT для sentiment;
- Natasha + pymorphy2 для NER и нормализации сущностей;
- Sentence-BERT для семантических эмбеддингов;
- UMAP для снижения размерности;
- HDBSCAN для плотностной кластеризации тем;
- PyArrow/Parquet для выгрузки результатов кластеризации;
- MLOps-контур: active learning, training orchestrator, model registry, model deployer.

### 2.3 Хранилища и графовый слой

- PostgreSQL 15 (сырые, промежуточные и аналитические данные);
- Neo4j 5.x (граф «тема-сообщение-канал-сущность»);
- Redis 7 (кэш и token blacklist);
- Object Storage (MinIO/S3) для артефактов моделей и датасетов.

### 2.4 API, UI и эксплуатация

- Auth Service: FastAPI, JWT (python-jose), bcrypt, slowapi;
- Analytics API: aiohttp;
- Frontend: Next.js 16, React 19, TypeScript, Tailwind CSS v4, TanStack Query, Recharts, Cytoscape.js;
- Observability: Prometheus, Grafana, Kafka UI, Neo4j Browser;
- Контейнеризация: Docker + Docker Compose.

## 3. Реализованные сервисы платформы

| Сервис | Назначение | Вход | Выход | Технологии |
|---|---|---|---|---|
| `rbc_telegram_collector` | Сбор сообщений из Telegram | Telegram MTProto | JSONL | Telethon |
| `kafka_bridge` | Перевод JSONL во внутренние события | JSONL | `raw.telegram.messages` | Python |
| `message_persister` | Надежная запись raw-слоя и идемпотентность | `raw.telegram.messages` | `persisted.messages` | aiokafka, asyncpg |
| `preprocessor` | Очистка и нормализация текста | `raw.telegram.messages`, `persisted.messages` | `preprocessed.messages` | regex/NLP utils, aiokafka |
| `sentiment_analyzer` | Тональность и вероятности классов | `preprocessed.messages` | `sentiment.enriched` | transformers, RuBERT |
| `ner_extractor` | Сущности и связи co-occurrence | `preprocessed.messages` | `ner.enriched` | Natasha, pymorphy2 |
| `topic_clusterer` | Кластеризация сообщений по темам | `preprocessed.messages` | `topic.assignments` | SBERT, UMAP, HDBSCAN |
| `topic_novelty_detector` | Детекция новых/дрейфующих тем | `topic.assignments` | `topic.novelty.candidates` | novelty rules, drift metrics |
| `active_learning_sampler` | Отбор кейсов на разметку | `topic.novelty.candidates` | `topic.labeling.tasks` | uncertainty sampling |
| `annotation_gateway` | Разметка и подтверждение тем | `topic.labeling.tasks` | `topic.labels` | API + reviewer UI |
| `dataset_builder` | Формирование версионированных датасетов | `topic.labels`, PG | `ml.training.jobs` | data pipelines |
| `training_orchestrator` | Планирование retrain и запуск job | `ml.training.jobs` | training run spec | scheduler/cron |
| `model_trainer` | Дообучение тематических моделей | training run spec | `ml.training.results` | PyTorch/transformers |
| `model_evaluator` | Проверка quality gates | `ml.training.results` | `ml.model.registry.events` | evaluation metrics |
| `model_registry` | Версионирование и lineage моделей | `ml.model.registry.events` | `model://topic/<version>` | registry + metadata |
| `model_deployer` | Canary rollout и rollback | `model://topic/<version>` | `ml.model.deployments` | deployment controller |
| `graph-builder` | Агрегация аналитики в графовые апдейты | `sentiment.enriched`, `ner.enriched` | `graph.updates` | event aggregation |
| `neo4j-writer` | Применение графовых обновлений | `graph.updates` | Neo4j graph | Cypher MERGE |
| `analytics_api` | Выдача аналитических представлений | PostgreSQL, Neo4j | REST `/analytics/*` | aiohttp |
| `auth_service` | Аутентификация, роли, админ-функции | REST `/api/auth/*` | JWT/права доступа | FastAPI |
| `frontend` | Визуальная аналитика и навигация | REST APIs | UI маршруты | Next.js/React |

## 4. Сквозной поток данных

```text
Telegram channels
    │
    ▼
rbc_telegram_collector -> kafka_bridge
    │
    ▼
raw.telegram.messages
    ├─► message_persister ─► persisted.messages
    └─► preprocessor (raw + persisted) ─► preprocessed.messages
             ├─► sentiment_analyzer ─► sentiment.enriched
             ├─► ner_extractor      ─► ner.enriched
             └─► topic_clusterer    ─► topic.assignments
                                           └─► topic_novelty_detector
                                                   └─► topic.novelty.candidates
                                                           └─► active_learning_sampler
                                                                   └─► topic.labeling.tasks
                                                                           └─► annotation_gateway
                                                                                   └─► topic.labels
                                                                                           └─► dataset_builder
                                                                                                   └─► ml.training.jobs
                                                                                                           └─► training_orchestrator
                                                                                                                   └─► model_trainer
                                                                                                                           └─► ml.training.results
                                                                                                                                   └─► model_evaluator
                                                                                                                                           └─► model_registry
                                                                                                                                                   └─► model_deployer
                                                                                                                                                           └─► topic_clusterer (new model version)

sentiment.enriched + ner.enriched
    └─► graph-builder ─► graph.updates ─► neo4j-writer ─► Neo4j

PostgreSQL + Neo4j
    └─► analytics_api ─► frontend
auth_service
    └─► frontend
```

## 5. Кластеризация тем

Тематический контур реализован как последовательность:

1. Векторизация `preprocessed.messages` через Sentence-BERT.
2. Группировка сообщений по временным окнам (`window_hours`).
3. Снижение размерности UMAP (`metric=cosine`).
4. Кластеризация HDBSCAN (`cluster_selection_method=leaf`).
5. Формирование `topic.assignments` с полями:
   - `topic_id` (кластер),
   - `confidence` / `cluster_probability`,
   - `run_id`,
   - `model_version`,
   - `event_timestamp`.
6. Сохранение результатов в `cluster_assignments`, запусков в `cluster_runs_pg`, публикация `topic.assignments`, экспорт в Parquet.

Параметры кластеризации управляются конфигурацией сервиса и версионируются вместе с `run_id`.

## 6. Определение новизны тем

### 6.1 Логика детекции

Сервис `topic_novelty_detector` оценивает новизну темы по комбинации сигналов:

- outlier-сигнал (`topic_id = -1`/noise);
- низкая уверенность кластера (`cluster_probability < threshold`);
- слабое соответствие историческим кластерам;
- быстрый рост нового кластера в коротком временном окне;
- дрейф распределения эмбеддингов относительно базового окна.

Результат публикуется в `topic.novelty.candidates` и содержит:

- `novelty_score`,
- `novelty_reason`,
- `cluster_snapshot`,
- `model_version`,
- `trace_id`.

### 6.2 Связь с дообучением

Кандидаты новизны проходят human-in-the-loop контур:

1. отбор кейсов (`active_learning_sampler`);
2. разметка (`annotation_gateway`);
3. сбор датасета (`dataset_builder`);
4. обучение и оценка (`model_trainer` + `model_evaluator`);
5. регистрация и деплой (`model_registry` + `model_deployer`).

Это обеспечивает замкнутый жизненный цикл тем: появление новой темы -> подтверждение -> адаптация модели -> улучшенное распознавание.

## 7. Хранилища и данные

### 7.1 PostgreSQL

Ключевые таблицы:

- `raw_messages`;
- `preprocessed_messages`;
- `sentiment_results`;
- `ner_results`;
- `entity_relations`;
- `cluster_runs_pg`;
- `cluster_assignments`;
- `processed_events`;
- `outbox`;
- `topic_label_tasks`, `topic_labels`, `model_versions`, `model_eval_reports`.

### 7.2 Neo4j

Графовые объекты:

- узлы: `Message`, `Entity`, `Channel`, `Topic`;
- связи: `POSTED_IN`, `MENTIONED_IN`, `RELATES_TO`, `CO_OCCURS_WITH`, `BELONGS_TO_TOPIC`.

### 7.3 Объектное хранилище

- версии датасетов для обучения;
- артефакты обученных моделей;
- манифесты и метаданные релизов.

## 8. API и пользовательская часть

### 8.1 Auth Service

Реализует:

- регистрацию/вход/refresh/logout;
- профиль и восстановление пароля;
- административные операции;
- аудит и реакции пользователей.

### 8.2 Analytics API

Предоставляет:

- обзор кластеров;
- документы кластера;
- связанные темы;
- топ-сущности;
- динамику тональности;
- графовые выборки для UI.

### 8.3 Frontend

Поддерживает прикладные сценарии:

- лента сообщений;
- обзор тем и карточка кластера;
- сущности;
- графовый обзор;
- диагностика новых тем;
- административные страницы.

## 9. Наблюдаемость и надежность

Платформа реализует эксплуатационный контур:

- health/metrics endpoints у процессоров;
- Prometheus + Grafana для метрик и алертов;
- Kafka UI для контроля топиков и consumer groups;
- Neo4j Browser для контроля графовой модели.

Надежность обеспечивается за счет:

- идемпотентности (`processed_events` + `UNIQUE`);
- retry с exponential backoff;
- DLQ-топиков;
- асинхронной декомпозиции через Kafka;
- canary/rollback в контуре деплоя моделей.

## 10. Результат реализации

Система реализована как единый технологический контур, в котором каждое сообщение проходит путь:

`внешний поток -> событие -> нормализация -> NLP-обогащение -> тема/новизна -> граф -> API -> пользовательский интерфейс`,

а контур дообучения обеспечивает адаптацию тематических моделей к новым и дрейфующим сюжетам.
