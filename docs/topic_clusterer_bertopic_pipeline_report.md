# BERTopic-like pipeline для topic_clusterer

Дата: 2026-05-02

## Цель

`topic_clusterer` был расширен до BERTopic-подобного pipeline для коротких и шумных Telegram-новостей. Старый сценарий не заменен: сервис по-прежнему потребляет `preprocessed.messages`, сохраняет совместимые `cluster_runs_pg` и `cluster_assignments`, публикует `topic.assignments` и остается совместимым с текущими API/frontend.

## Что изменилось в topic_clusterer

Pipeline разделен на независимые этапы в `topic_clusterer/topic_clusterer/pipeline.py`:

- `CorpusLoader` - подготовка корпуса из сообщений и precomputed embeddings.
- `EmbeddingBuilder` - сбор матрицы эмбеддингов.
- `DimensionalityReducer` - UMAP reduction с конфигурируемыми параметрами.
- `Clusterer` - HDBSCAN с fallback similarity clustering для малых батчей.
- `TopicRepresenter` - keywords, centroid, representative messages, channel/time summaries.
- `OutlierHandler` - мягкое присоединение outliers к ближайшим темам.
- `TopicMerger` - ограничение числа тем через `nr_topics`.
- `ResultPersister` - граница для сохранения результатов.

Для коротких новостей важен fallback: если батч слишком мал для HDBSCAN, сообщения не теряются, а кластеризуются по cosine similarity. Это сохраняет старое поведение singleton/малых кластеров и делает pipeline устойчивым к нерегулярному потоку Telegram.

## Конфигурация

Добавлены embedding-модели через `topic_clusterer/config.example.yaml`:

- `baseline`: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- `multilingual_mpnet`: `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`
- `labse`: `sentence-transformers/LaBSE`
- `rubert`: `ai-forever/sbert_large_nlu_ru`

Добавлены параметры без изменения кода:

- `n_neighbors`
- `n_components`
- `min_cluster_size`
- `min_samples`
- `top_n_words`
- `ngram_range`
- `nr_topics`
- `min_topic_size`
- `seed`
- `dataset_version`

Также зафиксированы Docker-зависимости `sentence-transformers<5` и `transformers<5`, потому что `transformers 5.x` в контейнере падал при импорте.

## Хранение результатов

Добавлена миграция `migrations/016_bertopic_like_topic_metadata.sql`.

На уровне запуска сохраняются:

- `model_version`
- `config_hash`
- `dataset_version`
- `embedding_model`
- `created_at`
- `metrics`

На уровне темы сохраняются:

- `centroid`
- `keywords`
- `representative_messages`
- `top_entities`
- `top_channels`
- `time_distribution`
- `confidence_score`
- `stability_score`
- полный конфиг запуска для воспроизводимости

Старые таблицы остаются рабочими:

- `cluster_runs_pg`
- `cluster_assignments`
- локальные SQLite `cluster_runs` и `cluster_results`
- parquet export из `topic_clusterer`

Если миграция `016` еще не применена, сервис не падает: расширенная metadata пропускается, а старый сценарий продолжает работать через `config_json` и `cluster_assignments`.

## API

Добавлены новые endpoints поверх существующего analytics API:

- `GET /analytics/topics`
- `GET /analytics/topics/{id}`
- `GET /analytics/topics/{id}/explanation`
- `GET /analytics/topics/{id}/similar`

Старые endpoints сохранены:

- `GET /analytics/overview/clusters`
- `GET /analytics/clusters/{id}`
- `GET /analytics/clusters/{id}/related`

В ответах теперь появляются объяснимые поля:

- `top_keywords`
- `confidence_score`
- `stability_score`
- `model.embedding_model`
- `model.model_version`
- `model.config_hash`
- `model.dataset_version`
- `model.config`

`/explanation` возвращает компактный блок для карточки темы: keywords, representative messages, top entities, top channels, time distribution и параметры модели.

## Как это увидит пользователь

### Страница `/topics`

Карточки тем стали информативнее:

- показываются ключевые слова темы;
- показывается stability score, если он рассчитан;
- отображается модель/версия запуска;
- темы по-прежнему открываются по старому `cluster_id`.

Для пользователя это означает, что список тем больше не выглядит как набор безымянных кластеров. Уже в списке видно, почему кластер считается отдельной темой: по keywords, сущностям, каналам и устойчивости.

### Страница `/topics/[clusterId]`

В детальной карточке добавлен блок `Model run`:

- embedding model;
- версия модели;
- config hash;
- dataset version;
- confidence;
- stability;
- основные параметры запуска: `n_neighbors`, `n_components`, `min_cluster_size`, `min_samples`, `top_n_words`, `nr_topics`, `seed`.

Также добавлен блок `Keywords`. Репрезентативные сообщения, связанные темы, топ сущности и топ каналы теперь подкреплены сохраненной metadata, а не только динамическими SQL-агрегациями.

Практический эффект: пользователь может понять, почему тема собрана именно так, какие сообщения ее представляют, какие каналы ее формируют и каким конфигом это было получено.

## Docker и инфраструктура

Контейнерно проверены:

- `topic-clusterer`
- `analytics-api`
- `ner-extractor`
- `frontend`

Были добавлены недостающие Kafka topics в `kafka/topics.yml` и `scripts/create_kafka_topics.sh`:

- `topic.assignments`
- `dlq.topic_clustering`

Без `topic.assignments` `topic_clusterer` мог построить кластеры, но застревал на публикации assignment events.

Для `ner-extractor` применялась миграция `017_entity_normalization.sql`, потому что новый нормализатор ожидает таблицу `entity_normalization_rules`.

## Проверки

Локально:

- `pytest tests/unit/test_topic_pipeline.py tests/integration/test_topic_pipeline_sqlite_persistence.py tests/unit/test_analysis_contracts.py -q` - `11 passed`
- `python -m compileall topic_clusterer/topic_clusterer analytics_api/analytics_api ner_extractor/ner_extractor` - ok
- `npm.cmd run lint -- --max-warnings=0` - ok
- `npx.cmd tsc --noEmit` - ok
- `git diff --check` - ok

В Docker:

- `docker compose -f docker-compose.infrastructure.yml config --quiet` - ok
- `docker compose ... build topic-clusterer analytics-api ner-extractor frontend` - ok
- все поднятые сервисы healthy;
- `GET http://localhost:8032/health` - `last_error: null`
- `GET http://localhost:8014/health` - `last_error: null`
- `GET http://localhost:8020/health` - ok
- `GET http://localhost:3000/topics` - `200`
- `GET /analytics/topics` возвращает keywords/model/config metadata;
- `GET /analytics/topics/{id}/explanation` возвращает объяснение темы.

Проверка хранения в Docker Postgres показала наличие данных в:

- `cluster_runs_pg`
- `cluster_assignments`
- `topic_cluster_metadata`

## Эксплуатационные замечания

Перед запуском полного контура должны быть применены миграции:

- `016_bertopic_like_topic_metadata.sql`
- `017_entity_normalization.sql`, если используется текущий `ner-extractor`

Kafka topics должны быть созданы через обновленный `scripts/create_kafka_topics.sh` или вручную:

- `topic.assignments`
- `dlq.topic_clustering`

Для воспроизводимых отчетов нужно фиксировать:

- `seed`
- `dataset_version`
- временное окно;
- список каналов;
- embedding model;
- полный config hash.

## Ограничения текущей реализации

- При `trigger_min_messages: 1` сервис может создавать много singleton-кластеров. Это совместимо со старым поведением, но для аналитических запусков лучше увеличивать `trigger_min_messages` и `min_cluster_size`.
- Keywords сейчас строятся легким TF-IDF-подобным способом внутри topic_clusterer. Это объяснимо и быстро, но не заменяет полноценный c-TF-IDF на больших batch-запусках.
- `nr_topics` реализован как deterministic merge ближайших малых тем, а не как полный BERTopic topic reduction.
- Для крупных батчей качество зависит от стабильности UMAP/HDBSCAN и выбранной embedding-модели.

