from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg
import numpy as np

from topic_benchmark_runner.config import AppConfig
from topic_benchmark_runner.metrics import build_metric_payload, safe_sklearn_metric


@dataclass
class DatasetRow:
    event_id: str
    channel: str
    message_id: int
    raw_message_id: str | None
    preprocessed_message_id: str | None
    message_date: datetime
    text: str


class TopicBenchmarkRunner:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    async def run_new_experiment(
        self,
        name: str,
        from_dt: str,
        to_dt: str,
        channels: list[str],
        models: list[str] | None = None,
        dataset_version: str = "manual",
        max_messages: int | None = None,
        seed: int | None = None,
        n_topics: int | None = None,
    ) -> str:
        model_keys = models or self._config.benchmark.default_models
        seed_value = seed if seed is not None else self._config.benchmark.seed
        max_rows = max_messages or self._config.benchmark.max_messages
        n_topics_value = n_topics or self._config.benchmark.n_topics
        from_value = _parse_dt(from_dt)
        to_value = _parse_dt(to_dt)

        pool = await asyncpg.create_pool(dsn=self._config.postgres.dsn(), min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                rows = await self._load_dataset(conn, from_value, to_value, channels, max_rows)
                experiment_id = await self._create_experiment(
                    conn, name, dataset_version, from_value, to_value, channels, seed_value
                )
                config_ids = await self._create_model_configs(
                    conn, experiment_id, model_keys, n_topics_value, seed_value
                )

            if len(rows) < self._config.benchmark.min_messages:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE topic_experiments SET status='failed', updated_at=NOW() WHERE id=$1",
                        experiment_id,
                    )
                return f"experiment_id={experiment_id} failed: not enough rows ({len(rows)})"

            previous_labels: list[int] | None = None
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE topic_experiments SET status='running', updated_at=NOW() WHERE id=$1",
                    experiment_id,
                )

            for model_key in model_keys:
                async with pool.acquire() as conn:
                    run_id = await conn.fetchval(
                        """
                        INSERT INTO topic_experiment_runs (
                            experiment_id, model_config_id, status, started_at, random_seed
                        ) VALUES ($1, $2, 'running', NOW(), $3)
                        RETURNING id
                        """,
                        experiment_id,
                        config_ids[model_key],
                        seed_value,
                    )
                try:
                    started = time.monotonic()
                    result = self._fit_model(model_key, rows, n_topics_value, seed_value)
                    cluster_run_id = self._cluster_run_id(experiment_id, model_key, rows)
                    duration = time.monotonic() - started
                    metrics = build_metric_payload(
                        [row.text for row in rows],
                        result["labels"],
                        result["topic_words"],
                        result.get("embeddings"),
                    )
                    if previous_labels is not None:
                        metrics["stability_ari_vs_previous"] = safe_sklearn_metric(
                            "ari", previous_labels, result["labels"]
                        )
                        metrics["stability_nmi_vs_previous"] = safe_sklearn_metric(
                            "nmi", previous_labels, result["labels"]
                        )
                    previous_labels = result["labels"]
                    async with pool.acquire() as conn:
                        await self._persist_run(
                            conn,
                            run_id,
                            cluster_run_id,
                            model_key,
                            rows,
                            result,
                            metrics,
                            from_value,
                            to_value,
                            duration,
                        )
                except Exception as exc:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE topic_experiment_runs
                            SET status='failed', finished_at=NOW(), error_message=$2
                            WHERE id=$1
                            """,
                            run_id,
                            str(exc)[:1000],
                        )

            async with pool.acquire() as conn:
                failed = await conn.fetchval(
                    "SELECT count(*) FROM topic_experiment_runs WHERE experiment_id=$1 AND status='failed'",
                    experiment_id,
                )
                await conn.execute(
                    "UPDATE topic_experiments SET status=$2, updated_at=NOW() WHERE id=$1",
                    experiment_id,
                    "failed" if failed and int(failed) == len(model_keys) else "completed",
                )
            return f"experiment_id={experiment_id}"
        finally:
            await pool.close()

    async def run_existing_experiment(self, experiment_id: str) -> str:
        pool = await asyncpg.create_pool(dsn=self._config.postgres.dsn(), min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                experiment = await conn.fetchrow(
                    """
                    SELECT id, name, dataset_version, dataset_version_id, window_start, window_end, channels, seed
                    FROM topic_experiments
                    WHERE id = $1
                    """,
                    experiment_id,
                )
                if experiment is None:
                    return f"experiment_id={experiment_id} not found"
                normalized_configs: list[dict[str, Any]] = []
                config_rows = await conn.fetch(
                    """
                    SELECT
                        ter.id AS run_id,
                        tmc.model_key,
                        tmc.params_json
                    FROM topic_experiment_runs ter
                    JOIN topic_model_configs tmc ON tmc.id = ter.model_config_id
                    WHERE ter.experiment_id = $1
                      AND ter.status IN ('queued', 'created', 'failed')
                    ORDER BY tmc.is_baseline DESC, tmc.model_key ASC
                    """,
                    experiment_id,
                )
                for row in config_rows:
                    normalized_configs.append(
                        {
                            "run_id": str(row["run_id"]),
                            "model_key": str(row["model_key"]),
                            "params_json": _json_object(row["params_json"]),
                        }
                    )
                max_messages = self._config.benchmark.max_messages
                if normalized_configs:
                    first_params = normalized_configs[0]["params_json"]
                    max_messages = int(first_params.get("max_messages") or max_messages)
                rows = await self._load_experiment_rows(conn, experiment, max_messages)
                await conn.execute(
                    "UPDATE topic_experiments SET status='running', updated_at=NOW() WHERE id=$1",
                    experiment_id,
                )

            if len(rows) < self._config.benchmark.min_messages:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE topic_experiments SET status='failed', updated_at=NOW() WHERE id=$1",
                        experiment_id,
                    )
                return f"experiment_id={experiment_id} failed: not enough rows ({len(rows)})"

            previous_labels: list[int] | None = None
            completed = 0
            for config_row in normalized_configs:
                model_key = config_row["model_key"]
                params = config_row["params_json"]
                n_topics = int(params.get("n_topics") or self._config.benchmark.n_topics)
                seed = int(experiment["seed"] or self._config.benchmark.seed)
                run_id = config_row["run_id"]
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE topic_experiment_runs SET status='running', started_at=NOW(), error_message=NULL WHERE id=$1",
                        run_id,
                    )
                try:
                    started = time.monotonic()
                    result = self._fit_model(model_key, rows, n_topics, seed)
                    cluster_run_id = self._cluster_run_id(experiment_id, model_key, rows)
                    duration = time.monotonic() - started
                    metrics = build_metric_payload(
                        [row.text for row in rows],
                        result["labels"],
                        result["topic_words"],
                        result.get("embeddings"),
                    )
                    if previous_labels is not None:
                        metrics["stability_ari_vs_previous"] = safe_sklearn_metric(
                            "ari", previous_labels, result["labels"]
                        )
                        metrics["stability_nmi_vs_previous"] = safe_sklearn_metric(
                            "nmi", previous_labels, result["labels"]
                        )
                    previous_labels = result["labels"]
                    async with pool.acquire() as conn:
                        await self._persist_run(
                            conn,
                            run_id,
                            cluster_run_id,
                            model_key,
                            rows,
                            result,
                            metrics,
                            experiment["window_start"],
                            experiment["window_end"],
                            duration,
                        )
                    completed += 1
                except Exception as exc:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE topic_experiment_runs
                            SET status='failed', finished_at=NOW(), error_message=$2
                            WHERE id=$1
                            """,
                            run_id,
                            str(exc)[:1000],
                        )

            async with pool.acquire() as conn:
                failed = await conn.fetchval(
                    "SELECT count(*) FROM topic_experiment_runs WHERE experiment_id=$1 AND status='failed'",
                    experiment_id,
                )
                total = await conn.fetchval(
                    "SELECT count(*) FROM topic_experiment_runs WHERE experiment_id=$1",
                    experiment_id,
                )
                status = "failed" if failed and int(failed) == int(total or 0) else "completed"
                await conn.execute(
                    "UPDATE topic_experiments SET status=$2, updated_at=NOW() WHERE id=$1",
                    experiment_id,
                    status,
                )
            return f"experiment_id={experiment_id} completed_runs={completed}"
        finally:
            await pool.close()

    async def run_worker(self, once: bool = False) -> str:
        processed = 0
        while True:
            experiment_id = await self._claim_next_experiment_id()
            if experiment_id is None:
                if once:
                    return f"processed={processed}"
                await asyncio.sleep(self._config.benchmark.worker_poll_interval_seconds)
                continue
            await self.run_existing_experiment(experiment_id)
            processed += 1
            if once:
                return f"processed={processed}"

    async def _load_dataset(
        self,
        conn: asyncpg.Connection,
        from_dt: datetime,
        to_dt: datetime,
        channels: list[str],
        limit: int,
    ) -> list[DatasetRow]:
        rows = await conn.fetch(
            """
            SELECT
                rm.event_id,
                rm.channel,
                rm.message_id,
                rm.id AS raw_message_id,
                pm.id AS preprocessed_message_id,
                rm.message_date,
                COALESCE(NULLIF(pm.normalized_text, ''), NULLIF(pm.cleaned_text, ''), rm.text, '') AS text
            FROM raw_messages rm
            LEFT JOIN preprocessed_messages pm ON pm.event_id = rm.event_id
            WHERE rm.message_date >= $1
              AND rm.message_date <= $2
              AND (cardinality($3::text[]) = 0 OR rm.channel = ANY($3::text[]))
              AND length(COALESCE(pm.normalized_text, pm.cleaned_text, rm.text, '')) >= 20
            ORDER BY rm.message_date ASC, rm.event_id ASC
            LIMIT $4
            """,
            from_dt,
            to_dt,
            channels,
            limit,
        )
        return [
            DatasetRow(
                event_id=row["event_id"],
                channel=row["channel"],
                message_id=int(row["message_id"]),
                raw_message_id=str(row["raw_message_id"]) if row["raw_message_id"] else None,
                preprocessed_message_id=str(row["preprocessed_message_id"]) if row["preprocessed_message_id"] else None,
                message_date=row["message_date"],
                text=row["text"],
            )
            for row in rows
        ]

    async def _load_dataset_version_rows(
        self,
        conn: asyncpg.Connection,
        dataset_version_id: str,
        limit: int,
    ) -> list[DatasetRow]:
        rows = await conn.fetch(
            """
            SELECT
                di.event_id,
                di.channel,
                di.message_id,
                rm.id AS raw_message_id,
                pm.id AS preprocessed_message_id,
                di.message_date,
                COALESCE(NULLIF(di.cleaned_text, ''), NULLIF(pm.normalized_text, ''), NULLIF(pm.cleaned_text, ''), di.text, rm.text, '') AS text
            FROM dataset_items di
            LEFT JOIN raw_messages rm ON rm.event_id = di.event_id
            LEFT JOIN preprocessed_messages pm ON pm.event_id = di.event_id
            WHERE di.dataset_version_id = $1::uuid
            ORDER BY di.message_date ASC, di.event_id ASC
            LIMIT $2
            """,
            dataset_version_id,
            limit,
        )
        return [
            DatasetRow(
                event_id=row["event_id"],
                channel=row["channel"],
                message_id=int(row["message_id"]),
                raw_message_id=str(row["raw_message_id"]) if row["raw_message_id"] else None,
                preprocessed_message_id=str(row["preprocessed_message_id"]) if row["preprocessed_message_id"] else None,
                message_date=row["message_date"],
                text=row["text"],
            )
            for row in rows
        ]

    async def _load_experiment_rows(
        self,
        conn: asyncpg.Connection,
        experiment: asyncpg.Record,
        max_messages: int,
    ) -> list[DatasetRow]:
        dataset_version_id = experiment.get("dataset_version_id")
        if dataset_version_id is not None:
            return await self._load_dataset_version_rows(conn, str(dataset_version_id), max_messages)
        return await self._load_dataset(
            conn,
            experiment["window_start"],
            experiment["window_end"],
            list(experiment["channels"] or []),
            max_messages,
        )

    async def _create_experiment(
        self,
        conn: asyncpg.Connection,
        name: str,
        dataset_version: str,
        from_dt: datetime,
        to_dt: datetime,
        channels: list[str],
        seed: int,
    ) -> str:
        return str(
            await conn.fetchval(
                """
                INSERT INTO topic_experiments (
                    name, dataset_version, window_start, window_end, channels, seed
                ) VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                name,
                dataset_version,
                from_dt,
                to_dt,
                channels,
                seed,
            )
        )

    async def _create_model_configs(
        self,
        conn: asyncpg.Connection,
        experiment_id: str,
        model_keys: list[str],
        n_topics: int,
        seed: int,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for key in model_keys:
            params = {
                "n_topics": n_topics,
                "seed": seed,
                "umap": {"n_neighbors": 15, "n_components": 10, "min_dist": 0.1},
                "hdbscan": {"min_cluster_size": 5, "min_samples": 3},
            }
            result[key] = str(
                await conn.fetchval(
                    """
                    INSERT INTO topic_model_configs (
                        experiment_id, model_key, model_name, embedding_model, params_json, is_baseline
                    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    RETURNING id
                    """,
                    experiment_id,
                    key,
                    _model_name(key),
                    self._config.benchmark.embedding_model if key in {"sbert_umap_hdbscan", "bertopic_like"} else None,
                    json.dumps(params),
                    key == "sbert_umap_hdbscan",
                )
            )
        return result

    async def _claim_next_experiment_id(self) -> str | None:
        pool = await asyncpg.create_pool(dsn=self._config.postgres.dsn(), min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        SELECT te.id
                        FROM topic_experiments te
                        WHERE te.status = 'created'
                          AND EXISTS (
                              SELECT 1
                              FROM topic_experiment_runs ter
                              WHERE ter.experiment_id = te.id
                                AND ter.status = 'queued'
                          )
                        ORDER BY te.created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """
                    )
                    if row is None:
                        return None
                    experiment_id = str(row["id"])
                    await conn.execute(
                        "UPDATE topic_experiments SET status='running', updated_at=NOW() WHERE id=$1",
                        experiment_id,
                    )
                    return experiment_id
        finally:
            await pool.close()

    def _fit_model(
        self,
        model_key: str,
        rows: list[DatasetRow],
        n_topics: int,
        seed: int,
    ) -> dict[str, Any]:
        texts = [row.text for row in rows]
        if model_key == "lda":
            return _fit_matrix_model(texts, n_topics, seed, "lda")
        if model_key == "nmf":
            return _fit_matrix_model(texts, n_topics, seed, "nmf")
        if model_key in {"sbert_umap_hdbscan", "bertopic_like"}:
            return _fit_embedding_cluster_model(
                texts,
                self._config.benchmark.embedding_model,
                seed,
                self._config.benchmark.use_gpu,
                use_c_tf_idf=model_key == "bertopic_like",
            )
        raise ValueError(f"unsupported model_key={model_key}")

    async def _persist_run(
        self,
        conn: asyncpg.Connection,
        experiment_run_id: str,
        cluster_run_id: str,
        model_key: str,
        rows: list[DatasetRow],
        result: dict[str, Any],
        metrics: dict[str, Any],
        from_dt: datetime,
        to_dt: datetime,
        duration: float,
    ) -> None:
        labels = result["labels"]
        probabilities = result.get("probabilities") or [1.0] * len(labels)
        n_clusters = len({label for label in labels if label >= 0})
        n_noise = sum(1 for label in labels if label == -1)
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO cluster_runs_pg (
                    run_id, run_timestamp, algo_version, window_start, window_end,
                    total_messages, total_clustered, total_noise, n_clusters, config_json, duration_seconds
                ) VALUES ($1, NOW(), $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                ON CONFLICT (run_id) DO UPDATE SET
                    run_timestamp=EXCLUDED.run_timestamp,
                    total_messages=EXCLUDED.total_messages,
                    total_clustered=EXCLUDED.total_clustered,
                    total_noise=EXCLUDED.total_noise,
                    n_clusters=EXCLUDED.n_clusters,
                    duration_seconds=EXCLUDED.duration_seconds
                """,
                cluster_run_id,
                f"benchmark:{model_key}",
                from_dt,
                to_dt,
                len(rows),
                len(rows) - n_noise,
                n_noise,
                n_clusters,
                json.dumps({"model_key": model_key}),
                duration,
            )
            for row, label, probability in zip(rows, labels, probabilities):
                await conn.execute(
                    """
                    INSERT INTO cluster_assignments (
                        run_id, cluster_id, event_id, channel, message_id,
                        raw_message_id, preprocessed_message_id, cluster_probability,
                        bucket_id, window_start, window_end, message_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'benchmark', $9, $10, $11)
                    ON CONFLICT (run_id, event_id) DO UPDATE SET
                        cluster_id=EXCLUDED.cluster_id,
                        cluster_probability=EXCLUDED.cluster_probability,
                        message_date=EXCLUDED.message_date
                    """,
                    cluster_run_id,
                    int(label),
                    row.event_id,
                    row.channel,
                    row.message_id,
                    row.raw_message_id,
                    row.preprocessed_message_id,
                    float(probability),
                    from_dt,
                    to_dt,
                    row.message_date,
                )
            await conn.execute(
                """
                UPDATE topic_experiment_runs
                SET status='completed',
                    finished_at=NOW(),
                    duration_seconds=$2,
                    cluster_run_id=$3,
                    runtime_json=$4::jsonb
                WHERE id=$1
                """,
                experiment_run_id,
                duration,
                cluster_run_id,
                json.dumps({"message_count": len(rows), "model_key": model_key}),
            )
            for name, value in metrics.items():
                if isinstance(value, (dict, list)):
                    metric_value = None
                    metric_json = json.dumps(value)
                else:
                    metric_value = float(value) if value is not None else None
                    metric_json = None
                await conn.execute(
                    """
                    INSERT INTO topic_metrics (experiment_run_id, metric_name, metric_value, metric_json)
                    VALUES ($1, $2, $3, $4::jsonb)
                    ON CONFLICT (experiment_run_id, metric_name) DO UPDATE SET
                        metric_value=EXCLUDED.metric_value,
                        metric_json=EXCLUDED.metric_json,
                        calculated_at=NOW()
                    """,
                    experiment_run_id,
                    name,
                    metric_value,
                    metric_json,
                )
            await conn.execute(
                """
                INSERT INTO topic_experiment_artifacts (experiment_run_id, artifact_type, payload_json)
                VALUES ($1, 'topic_words', $2::jsonb)
                """,
                experiment_run_id,
                json.dumps(result.get("topic_words", []), ensure_ascii=False),
            )

    def _cluster_run_id(self, experiment_id: str, model_key: str, rows: list[DatasetRow]) -> str:
        raw = "|".join([experiment_id, model_key, *[row.event_id for row in rows]])
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"bench_{model_key}_{digest}"[:255]


def _fit_matrix_model(texts: list[str], n_topics: int, seed: int, kind: str) -> dict[str, Any]:
    from sklearn.decomposition import LatentDirichletAllocation, NMF
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(max_df=0.9, min_df=2, max_features=8000, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(texts)
    topic_count = max(2, min(n_topics, max(2, len(texts) // 5)))
    if kind == "lda":
        model = LatentDirichletAllocation(n_components=topic_count, random_state=seed, learning_method="batch")
        doc_topic = model.fit_transform(matrix)
        components = model.components_
    else:
        model = NMF(n_components=topic_count, random_state=seed, init="nndsvda", max_iter=300)
        doc_topic = model.fit_transform(matrix)
        components = model.components_
    labels = doc_topic.argmax(axis=1).astype(int).tolist()
    probabilities = doc_topic.max(axis=1).astype(float).tolist()
    names = np.array(vectorizer.get_feature_names_out())
    topic_words = [names[component.argsort()[::-1][:12]].tolist() for component in components]
    return {"labels": labels, "probabilities": probabilities, "topic_words": topic_words, "embeddings": doc_topic}


def _fit_embedding_cluster_model(
    texts: list[str],
    embedding_model: str,
    seed: int,
    use_gpu: bool,
    use_c_tf_idf: bool,
) -> dict[str, Any]:
    import hdbscan
    import umap
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer

    device = "cuda" if use_gpu else "cpu"
    model = SentenceTransformer(embedding_model, device=device)
    embeddings = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    n_neighbors = min(15, max(2, len(texts) - 1))
    reduced = umap.UMAP(
        n_neighbors=n_neighbors,
        n_components=min(10, max(2, len(texts) - 2)),
        min_dist=0.1,
        metric="cosine",
        random_state=seed,
    ).fit_transform(embeddings)
    clusterer = hdbscan.HDBSCAN(min_cluster_size=5, min_samples=3, prediction_data=True)
    clusterer.fit(reduced)
    labels = clusterer.labels_.astype(int).tolist()
    probabilities = clusterer.probabilities_.astype(float).tolist()
    topic_words: list[list[str]] = []
    for label in sorted({label for label in labels if label >= 0}):
        cluster_texts = [text for text, item_label in zip(texts, labels) if item_label == label]
        if not cluster_texts:
            continue
        topic_words.append(_extract_topic_words(cluster_texts, use_c_tf_idf))
    return {"labels": labels, "probabilities": probabilities, "topic_words": topic_words, "embeddings": reduced}


def _model_name(key: str) -> str:
    return {
        "sbert_umap_hdbscan": "SBERT + UMAP + HDBSCAN baseline",
        "bertopic_like": "BERTopic-like embeddings + c-TF-IDF",
        "lda": "Latent Dirichlet Allocation",
        "nmf": "Non-negative Matrix Factorization",
    }.get(key, key)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_topic_words(cluster_texts: list[str], use_c_tf_idf: bool) -> list[str]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    documents = cluster_texts if use_c_tf_idf else [" ".join(cluster_texts)]
    max_df = 1.0 if len(documents) <= 1 else 0.95
    vectorizer = TfidfVectorizer(
        max_df=max_df,
        min_df=1,
        max_features=5000,
        ngram_range=(1, 2),
    )
    matrix = vectorizer.fit_transform(documents)
    scores = np.asarray(matrix.sum(axis=0)).ravel()
    names = np.array(vectorizer.get_feature_names_out())
    return names[scores.argsort()[::-1][:12]].tolist()
