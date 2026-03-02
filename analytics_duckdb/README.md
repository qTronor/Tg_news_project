## Analytics DuckDB service

Read-only аналитический API поверх Parquet lake.  
OLTP в Postgres не заменяется: DuckDB используется только для UI-аналитики.

### 1) Заливка Colab outputs в lake

Colab folder должен содержать артефакты:

- `telegram_clean.parquet`
- `topic_predictions.parquet`
- `sentiment_predictions.parquet`
- `doc_entities.parquet`
- `clusters.parquet`
- `final_table.parquet`

Запуск инжеста:

```bash
python analytics_duckdb/ingest.py --colab-outputs-path ./colab_outputs --lake-path ./lake
```

Будет создан lake layout:

- `lake/clean/dt=YYYY-MM-DD/channel=.../*.parquet`
- `lake/predictions/topic/dt=.../*.parquet`
- `lake/predictions/sentiment/dt=.../*.parquet`
- `lake/entities/dt=.../*.parquet`
- `lake/clusters/dt=.../window_hours=.../*.parquet`
- `lake/ui/final/dt=.../*.parquet`
- `lake/_meta/watermarks.json`

Если `date` отсутствует/не парсится, используется `dt=unknown`.

### 2) Запуск API

Локально:

```bash
pip install -r analytics_duckdb/requirements.txt
python analytics_duckdb/main.py --config analytics_duckdb/config.example.yaml
```

Через Docker Compose (с инфраструктурой):

```bash
docker compose -f docker-compose.infrastructure.yml -f analytics_duckdb/docker-compose.yml up --build analytics-duckdb
```

### 3) ENV

- `LAKE_PATH` / `ANALYTICS_DUCKDB__LAKE_PATH`
- `COLAB_OUTPUTS_PATH` (для ingest CLI)
- `DUCKDB_THREADS` / `ANALYTICS_DUCKDB__DUCKDB__THREADS`
- `DUCKDB_MEMORY_LIMIT` / `ANALYTICS_DUCKDB__DUCKDB__MEMORY_LIMIT`

### 4) Примеры curl

Health:

```bash
curl "http://localhost:8020/healthz"
```

Обзор тем/кластеров:

```bash
curl "http://localhost:8020/analytics/overview/clusters?from=2026-01-01&to=2026-01-31&channel=rbc_news"
```

Топ сущностей:

```bash
curl "http://localhost:8020/analytics/entities/top?from=2026-01-01&to=2026-01-31&topic=Экономика&entity_type=ORG"
```

Динамика тональности:

```bash
curl "http://localhost:8020/analytics/sentiment/dynamics?from=2026-01-01&to=2026-01-31&bucket=day&cluster_id=42"
```

Лента документов по кластеру:

```bash
curl "http://localhost:8020/analytics/clusters/42/documents?from=2026-01-01&to=2026-01-31&limit=20&offset=0"
```

Связанные кластера:

```bash
curl "http://localhost:8020/analytics/clusters/42/related?from=2026-01-01&to=2026-01-31&limit=10"
```
