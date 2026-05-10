# Topic Modeling Benchmark

Benchmark-контур сравнивает несколько методов тематического моделирования на одном и том же срезе Telegram-сообщений и сохраняет результаты в PostgreSQL.

## Что запускается

Минимальный воспроизводимый набор:

- `sbert_umap_hdbscan` - текущий baseline: multilingual SBERT embeddings, UMAP, HDBSCAN.
- `bertopic_like` - embeddings + HDBSCAN + c-TF-IDF-подобные topic words.
- `lda` - CPU-friendly Latent Dirichlet Allocation по TF-IDF матрице.
- `nmf` - CPU-friendly Non-negative Matrix Factorization по TF-IDF матрице.

`top2vec` и `ctm` оставлены как optional model keys на уровне API-конфига, но runner их не исполняет без отдельного добавления зависимостей. Это осознанное ограничение для ноутбука с RTX 3050 Laptop и i5 10th gen.

## Миграция

```powershell
docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f migrations/013_topic_benchmark.sql
docker exec -i telegram-news-postgres psql -U postgres -d telegram_news -f migrations/015_topic_benchmark_dataset_link.sql
```

## Запуск

Через API можно создать эксперимент и queued runs:

```http
POST /analytics/experiments/topics/run
```

Пример payload:

```json
{
  "name": "weekly-topic-benchmark",
  "from": "2026-04-20T00:00:00Z",
  "to": "2026-04-27T00:00:00Z",
  "channels": ["rbc_news", "banksta"],
  "models": ["sbert_umap_hdbscan", "lda", "nmf"],
  "seed": 42,
  "dataset_version": "2026-04-20_2026-04-27",
  "max_messages": 1500,
  "n_topics": 12
}
```

Если benchmark должен использовать готовый датасет из `dataset_versions`, вместо ручного окна и каналов можно передать `dataset_version_id`:

```json
{
  "name": "dataset-driven-benchmark",
  "from": "2026-04-20T00:00:00Z",
  "to": "2026-04-27T00:00:00Z",
  "dataset_version_id": "00000000-0000-0000-0000-000000000000",
  "models": ["sbert_umap_hdbscan", "lda", "nmf"],
  "max_messages": 1500,
  "seed": 42
}
```

В этом режиме benchmark берет сообщения из `dataset_items`, а окно времени и список каналов подтягивает из выбранного dataset автоматически.

Фактический расчет уже созданного через API эксперимента выполняет runner:

```powershell
python -m topic_benchmark_runner.main --config topic_benchmark_runner/config.example.yaml run-existing --experiment-id <experiment_id>
```

В Docker:

```powershell
docker compose -f docker-compose.infrastructure.yml --profile benchmark run --rm topic-benchmark-runner run-existing --experiment-id <experiment_id>
```

Можно также создать и сразу выполнить новый эксперимент без API:

```powershell
python -m topic_benchmark_runner.main --config topic_benchmark_runner/config.example.yaml run --from 2026-04-20T00:00:00Z --to 2026-04-27T00:00:00Z --channels rbc_news,banksta --models sbert_umap_hdbscan,lda,nmf --dataset-version 2026-04-20_2026-04-27 --max-messages 1500
```

## API

- `GET /analytics/experiments/topics` - список экспериментов.
- `GET /analytics/experiments/topics/{id}` - параметры и runs эксперимента.
- `POST /analytics/experiments/topics/run` - создать эксперимент и queued runs.
- `GET /analytics/experiments/topics/{id}/metrics` - таблица метрик по моделям.

Frontend: `/experiments/topic-modeling`.

## Метрики

- `topic_coherence` - UMass-like coherence по совместной встречаемости top words. Ближе к 0 обычно лучше, сильно отрицательные значения хуже.
- `topic_diversity` - доля уникальных слов среди top words. Выше значит меньше дублирования тем.
- `silhouette` - качество разделения кластеров по embedding/doc-topic пространству. Выше лучше.
- `davies_bouldin` - компактность и разделимость кластеров. Ниже лучше.
- `outlier_ratio` - доля labels `-1`. Ниже лучше, но ноль у LDA/NMF ожидаем и не означает автоматически лучшее качество.
- `cluster_count` - количество найденных тем без outliers.
- `stability_ari_vs_previous` и `stability_nmi_vs_previous` - сравнение labels с предыдущим run в том же эксперименте.

Если появится ручная разметка, ARI/NMI можно считать теми же функциями `safe_sklearn_metric()` между labels модели и gold labels.

## Практические ограничения

Для RTX 3050 Laptop и i5 10th gen рекомендуемый старт:

- `max_messages`: 1000-2500.
- `models`: сначала `lda,nmf`, затем добавлять `sbert_umap_hdbscan`.
- `use_gpu`: `false` по умолчанию, чтобы не конкурировать с другими ML-сервисами; включать только если CUDA окружение стабильно.
- Фиксировать `seed`, `dataset_version`, окно времени и список каналов для отчета.
