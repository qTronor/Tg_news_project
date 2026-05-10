from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Optional

try:
    import asyncpg
except ImportError:  # pragma: no cover - pure unit tests can run without DB driver
    asyncpg = None  # type: ignore[assignment]


TaskType = Literal[
    "topic_classification",
    "sentiment_classification",
    "embedding_finetuning",
    "ner_finetuning",
]
ValidationStatus = Literal["valid", "warning", "invalid"]

TASK_TO_MODEL_TYPE: dict[str, str] = {
    "topic_classification": "topic_classifier",
    "sentiment_classification": "sentiment_classifier",
    "embedding_finetuning": "embedding_model",
    "ner_finetuning": "ner_model",
}

DEFAULT_BASE_MODELS: dict[str, str] = {
    "topic_classification": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentiment_classification": "cointegrated/rubert-tiny-sentiment-balanced",
    "embedding_finetuning": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "ner_finetuning": "dslim/bert-base-NER",
}

DEFAULT_METRICS: dict[str, list[str]] = {
    "topic_classification": ["accuracy", "macro_f1", "weighted_f1", "per_class_f1"],
    "sentiment_classification": ["accuracy", "macro_f1", "weighted_f1", "per_class_f1"],
    "embedding_finetuning": [
        "silhouette_before",
        "silhouette_after",
        "ari",
        "nmi",
        "outlier_ratio_after",
    ],
    "ner_finetuning": ["entity_f1", "precision", "recall"],
}


def utc_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    return uuid.UUID(str(value))


def _norm_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _label_for_task(row: dict[str, Any], task_type: str) -> Optional[str]:
    label_type = row.get("label_type")
    label_value = row.get("label_value")
    if task_type == "topic_classification":
        if label_type in {"topic_label", "broad_topic", "storyline"} and label_value:
            return str(label_value)
        return row.get("broad_topic") or row.get("storyline") or row.get("reviewed_topic_label")
    if task_type == "sentiment_classification":
        if label_type in {"sentiment", "sentiment_label"} and label_value:
            return str(label_value)
        return row.get("sentiment")
    if task_type == "embedding_finetuning":
        if label_type in {"cluster_label", "pair_similarity"} and label_value:
            return str(label_value)
        return row.get("cluster_label") or row.get("broad_topic") or row.get("cluster_id")
    if task_type == "ner_finetuning":
        if row.get("span_start") is not None and row.get("span_end") is not None and label_value:
            return str(label_value)
        entities = row.get("entities_json") or []
        if isinstance(entities, str):
            entities = _json(entities)
        if entities:
            return "spans"
    return None


def _task_quality_filter(row: dict[str, Any]) -> bool:
    return row.get("quality") in (None, "useful")


def validate_dataset_records(
    dataset: dict[str, Any],
    rows: Iterable[dict[str, Any]],
    task_type: str,
) -> dict[str, Any]:
    records = [dict(row) for row in rows]
    labels_by_item: dict[str, set[str]] = defaultdict(set)
    split_by_item: dict[str, str] = {}
    text_by_item: dict[str, str] = {}
    event_by_item: dict[str, str] = {}
    spans_count = 0

    for row in records:
        item_id = str(row.get("item_id") or row.get("id"))
        split_by_item[item_id] = row.get("split") or "unassigned"
        text_by_item[item_id] = row.get("text") or ""
        event_by_item[item_id] = row.get("event_id") or item_id
        if not _task_quality_filter(row):
            continue
        label = _label_for_task(row, task_type)
        if label:
            labels_by_item[item_id].add(str(label))
        if task_type == "ner_finetuning":
            entities = row.get("entities_json") or []
            if isinstance(entities, str):
                entities = _json(entities)
            spans_count += len(entities) if isinstance(entities, list) else 0
            if row.get("span_start") is not None and row.get("span_end") is not None:
                spans_count += 1

    item_count = len(text_by_item)
    empty_text_count = sum(1 for text in text_by_item.values() if not str(text).strip())
    distribution: Counter[str] = Counter()
    for labels in labels_by_item.values():
        for label in labels:
            distribution[label] += 1

    warnings: list[str] = []
    errors: list[str] = []

    if item_count == 0:
        errors.append("Dataset has no items.")
    if empty_text_count:
        errors.append(f"Dataset contains {empty_text_count} empty text item(s).")

    if task_type in {"topic_classification", "sentiment_classification"}:
        if not distribution:
            errors.append("Dataset has no labels for the selected task.")
        if len(distribution) < 2:
            errors.append("At least two classes are required.")
        if task_type == "topic_classification":
            small = {label: count for label, count in distribution.items() if count < 10}
            if small:
                errors.append(
                    "Topic classification MVP requires at least 10 examples per class."
                )
        if task_type == "sentiment_classification":
            missing = {"positive", "negative", "neutral"} - set(distribution)
            if missing:
                warnings.append(
                    "Sentiment dataset should ideally include positive, negative and neutral labels."
                )
        if distribution:
            min_count = min(distribution.values())
            max_count = max(distribution.values())
            if min_count > 0 and max_count / min_count > 5:
                warnings.append("Class imbalance is stronger than 5x.")
    elif task_type == "embedding_finetuning":
        if not distribution:
            errors.append("Embedding finetuning requires pair labels or confirmed cluster labels.")
        elif len(distribution) < 2:
            errors.append("Embedding finetuning needs at least two confirmed clusters or both pair classes.")
        else:
            pair_positive = distribution.get("similar", 0) + distribution.get("positive", 0)
            pair_negative = distribution.get("dissimilar", 0) + distribution.get("negative", 0)
            if pair_positive == 0 or pair_negative == 0:
                warnings.append(
                    "Only cluster labels were found; positive/negative pairs will be generated automatically."
                )
    elif task_type == "ner_finetuning":
        if spans_count == 0:
            errors.append("NER finetuning requires span labels.")
        elif spans_count < 20:
            warnings.append("NER span count is low for training; keep this as an experimental candidate.")
    else:
        errors.append(f"Unsupported task_type: {task_type}")

    split_counts = Counter(split_by_item.values())
    required_splits = {"train", "validation", "test"}
    if task_type != "ner_finetuning" and not required_splits.issubset(set(split_counts)):
        warnings.append("Train/validation/test split is incomplete; API will use a deterministic fallback split.")
    if item_count >= 3 and split_counts.get("test", 0) == 0:
        warnings.append("No explicit test split was found.")
    if task_type in {"topic_classification", "sentiment_classification"}:
        labeled_items = sum(1 for labels in labels_by_item.values() if labels)
        if labeled_items < 3:
            errors.append("Not enough labeled examples to create train/validation/test split.")

    normalized_by_split: dict[str, set[str]] = defaultdict(set)
    for item_id, text in text_by_item.items():
        normalized = _norm_text(text)
        if not normalized:
            continue
        normalized_by_split[split_by_item.get(item_id, "unassigned")].add(normalized)
    leakage = (
        normalized_by_split.get("train", set())
        & (normalized_by_split.get("test", set()) | normalized_by_split.get("temporal_test", set()))
    )
    if leakage:
        errors.append("Identical normalized messages appear in train and test splits.")

    status: ValidationStatus = "invalid" if errors else ("warning" if warnings else "valid")
    report = {
        "dataset_id": str(dataset.get("id")),
        "dataset_name": dataset.get("name"),
        "task_type": task_type,
        "status": status,
        "dataset_size": item_count,
        "labeled_items": sum(1 for labels in labels_by_item.values() if labels),
        "label_distribution": dict(sorted(distribution.items())),
        "split_distribution": dict(sorted(split_counts.items())),
        "empty_text_count": empty_text_count,
        "warnings": warnings,
        "errors": errors,
        "metrics": DEFAULT_METRICS.get(task_type, []),
        "leakage": {
            "duplicate_train_test_count": len(leakage),
        },
        "notes": [
            "Training is never started by validation.",
            "A trained model remains candidate until explicit deployment consent.",
        ],
    }
    return report


def build_training_plan(
    dataset: dict[str, Any],
    validation_report: dict[str, Any],
    task_type: str,
    base_model: Optional[str] = None,
    training_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    config = {
        "mode": "mock",
        "epochs": 3,
        "batch_size": 16,
        "learning_rate": 2e-5,
        "early_stopping": True,
    }
    if task_type == "embedding_finetuning":
        config.update({"loss": "contrastive_or_triplet", "epochs": 2})
    if training_config:
        config.update(training_config)
    return {
        "dataset_id": str(dataset.get("id")),
        "dataset_name": dataset.get("name"),
        "dataset_size": validation_report.get("dataset_size", 0),
        "task_type": task_type,
        "label_distribution": validation_report.get("label_distribution", {}),
        "split": validation_report.get("split_distribution", {}),
        "base_model": base_model or DEFAULT_BASE_MODELS.get(task_type, "mock-base-model"),
        "training_config": config,
        "metrics": DEFAULT_METRICS.get(task_type, []),
        "warnings": validation_report.get("warnings", []),
        "validation_status": validation_report.get("status"),
        "will_auto_deploy": False,
        "production_notice": (
            "Модель после обучения НЕ будет автоматически внедрена. "
            "Она будет зарегистрирована как candidate."
        ),
    }


def compare_to_baseline(
    candidate_metrics: dict[str, Any],
    baseline_metrics: Optional[dict[str, Any]],
    primary_metric: str,
) -> dict[str, Any]:
    baseline_value = None if not baseline_metrics else baseline_metrics.get(primary_metric)
    candidate_value = candidate_metrics.get(primary_metric)
    delta = None
    warning = False
    if isinstance(baseline_value, (int, float)) and isinstance(candidate_value, (int, float)):
        delta = candidate_value - baseline_value
        warning = delta < 0
    return {
        "metric_name": primary_metric,
        "baseline_value": baseline_value,
        "candidate_value": candidate_value,
        "delta": delta,
        "deployment_warning": warning,
    }


@dataclass(frozen=True)
class TrainingResult:
    artifact_path: str
    metrics: dict[str, Any]
    confusion_matrix: dict[str, Any]


class MockTrainer:
    def train(
        self,
        *,
        job_id: str,
        task_type: str,
        base_model: str,
        label_distribution: dict[str, int],
        training_config: dict[str, Any],
    ) -> TrainingResult:
        if training_config.get("force_fail"):
            raise RuntimeError("MockTrainer forced failure")
        total = max(sum(int(v) for v in label_distribution.values()), 1)
        class_count = max(len(label_distribution), 1)
        majority = max([int(v) for v in label_distribution.values()] or [1])
        balance_penalty = majority / total
        base_score = max(0.35, min(0.95, 0.84 - (balance_penalty - 1 / class_count) * 0.25))
        if task_type == "embedding_finetuning":
            metrics = {
                "silhouette_before": 0.12,
                "silhouette_after": round(base_score - 0.25, 4),
                "ari": round(base_score - 0.18, 4),
                "nmi": round(base_score - 0.12, 4),
                "outlier_ratio_after": 0.08,
                "primary_metric": "silhouette_after",
            }
        elif task_type == "ner_finetuning":
            metrics = {
                "entity_f1": round(base_score - 0.08, 4),
                "precision": round(base_score - 0.06, 4),
                "recall": round(base_score - 0.10, 4),
                "primary_metric": "entity_f1",
            }
        else:
            per_class = {label: round(base_score - (0.02 if count < 12 else 0), 4) for label, count in label_distribution.items()}
            metrics = {
                "accuracy": round(base_score, 4),
                "macro_f1": round(sum(per_class.values()) / max(len(per_class), 1), 4),
                "weighted_f1": round(base_score - 0.01, 4),
                "per_class_f1": per_class,
                "primary_metric": "macro_f1",
            }
        confusion = {
            "labels": sorted(label_distribution),
            "matrix": [[int(label_distribution.get(label, 0)) if i == j else 0 for j, label in enumerate(sorted(label_distribution))] for i, _ in enumerate(sorted(label_distribution))],
        }
        return TrainingResult(
            artifact_path=f"models/candidates/{task_type}/{job_id}",
            metrics=metrics,
            confusion_matrix=confusion,
        )


class DatasetValidator:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def validate(self, dataset_id: str, task_type: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            dataset = await fetch_dataset(conn, dataset_id)
            rows = await fetch_dataset_label_rows(conn, dataset_id)
            report = validate_dataset_records(dict(dataset), [dict(r) for r in rows], task_type)
            await conn.execute(
                """
                INSERT INTO dataset_validation_reports (dataset_id, task_type, status, report_json)
                VALUES ($1::uuid, $2, $3, $4::jsonb)
                """,
                dataset_id,
                task_type,
                report["status"],
                json.dumps(report),
            )
            return report

    async def latest(self, dataset_id: str, task_type: str) -> Optional[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, dataset_id, task_type, status, report_json, created_at
                FROM dataset_validation_reports
                WHERE dataset_id = $1::uuid AND task_type = $2
                ORDER BY created_at DESC
                LIMIT 1
                """,
                dataset_id,
                task_type,
            )
            return validation_report_payload(row) if row else None


class TrainingOrchestrator:
    def __init__(self, pool: asyncpg.Pool, trainer: Optional[MockTrainer] = None) -> None:
        self._pool = pool
        self._trainer = trainer or MockTrainer()

    async def preview(
        self,
        dataset_id: str,
        task_type: str,
        base_model: Optional[str],
        training_config: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            dataset = dict(await fetch_dataset(conn, dataset_id))
            validation = await latest_or_create_validation(conn, dataset_id, task_type)
            return build_training_plan(dataset, validation, task_type, base_model, training_config)

    async def create_job(
        self,
        *,
        dataset_id: str,
        task_type: str,
        base_model: str,
        training_config: dict[str, Any],
        consent_to_train: bool,
        actor_user_id: Optional[str],
    ) -> dict[str, Any]:
        if consent_to_train is not True:
            raise ValueError("consent_to_train=true is required and no job was created")
        actor_uuid = _uuid_or_none(actor_user_id) or uuid.UUID(int=0)
        async with self._pool.acquire() as conn:
            validation = await latest_or_create_validation(conn, dataset_id, task_type)
            if validation["status"] == "invalid":
                raise ValueError("dataset validation status is invalid; training job was not created")
            job_id = await conn.fetchval(
                """
                INSERT INTO training_jobs (
                    dataset_id, task_type, base_model, training_config_json, status,
                    consent_to_train_by, consent_to_train_at
                )
                VALUES ($1::uuid, $2, $3, $4::jsonb, 'queued', $5, NOW())
                RETURNING id
                """,
                dataset_id,
                task_type,
                base_model,
                json.dumps(training_config or {}),
                actor_uuid,
            )
            await self.log(conn, job_id, "info", "Training job queued after explicit consent.", {})
            return await self.fetch_job(conn, str(job_id))

    async def run_job(self, job_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            job = await self.fetch_job(conn, job_id)
            if job["status"] not in {"queued", "running", "evaluating"}:
                return job
            if job["status"] == "queued":
                claimed = await conn.fetchval(
                    """
                    UPDATE training_jobs
                    SET status='running', started_at=COALESCE(started_at, NOW())
                    WHERE id=$1::uuid AND status='queued'
                    RETURNING id
                    """,
                    job_id,
                )
                if not claimed:
                    return await self.fetch_job(conn, job_id)
            await self.log(conn, job_id, "info", "Training started.", {})
        started = time.monotonic()
        try:
            async with self._pool.acquire() as conn:
                validation = await latest_or_create_validation(conn, job["dataset_id"], job["task_type"])
                result = await asyncio.to_thread(
                    self._trainer.train,
                    job_id=job_id,
                    task_type=job["task_type"],
                    base_model=job["base_model"],
                    label_distribution=validation.get("label_distribution", {}),
                    training_config=job["training_config"],
                )
                await conn.execute(
                    "UPDATE training_jobs SET status='evaluating' WHERE id=$1::uuid",
                    job_id,
                )
                await self.log(conn, job_id, "info", "Evaluation started.", {})
                model = await register_candidate_model(
                    conn,
                    training_job_id=job_id,
                    task_type=job["task_type"],
                    base_model=job["base_model"],
                    artifact_path=result.artifact_path,
                    metrics=result.metrics,
                )
                await conn.execute(
                    """
                    INSERT INTO model_evaluation_results (
                        model_version_id, dataset_id, split, metrics_json, confusion_matrix_json
                    )
                    VALUES ($1::uuid, $2::uuid, 'validation', $3::jsonb, $4::jsonb)
                    """,
                    model["id"],
                    job["dataset_id"],
                    json.dumps(result.metrics),
                    json.dumps(result.confusion_matrix),
                )
                await conn.execute(
                    """
                    UPDATE training_jobs
                    SET status='completed', finished_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    job_id,
                )
                await self.log(
                    conn,
                    job_id,
                    "info",
                    "Training completed; candidate model created. No deployment was performed.",
                    {"duration_seconds": time.monotonic() - started, "model_version_id": model["id"]},
                )
                return await self.fetch_job(conn, job_id)
        except Exception as exc:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE training_jobs
                    SET status='failed', error_message=$2, finished_at=NOW()
                    WHERE id=$1::uuid
                    """,
                    job_id,
                    str(exc),
                )
                await self.log(conn, job_id, "error", "Training failed.", {"error": str(exc)})
                return await self.fetch_job(conn, job_id)

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE training_jobs
                SET status='cancelled', finished_at=NOW()
                WHERE id=$1::uuid AND status IN ('draft', 'waiting_for_consent', 'queued', 'running')
                """,
                job_id,
            )
            await self.log(conn, job_id, "warning", "Training job cancelled.", {})
            return await self.fetch_job(conn, job_id)

    async def log(
        self,
        conn: asyncpg.Connection,
        job_id: Any,
        level: str,
        message: str,
        metadata: dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO training_job_logs (training_job_id, level, message, metadata_json)
            VALUES ($1::uuid, $2, $3, $4::jsonb)
            """,
            str(job_id),
            level,
            message,
            json.dumps(metadata or {}),
        )

    async def fetch_job(self, conn: asyncpg.Connection, job_id: str) -> dict[str, Any]:
        row = await conn.fetchrow(
            """
            SELECT
                tj.*,
                dv.name AS dataset_name,
                mv.id AS model_version_id,
                mv.version AS model_version,
                mv.status AS model_status,
                mv.metrics_json AS model_metrics
            FROM training_jobs tj
            JOIN dataset_versions dv ON dv.id = tj.dataset_id
            LEFT JOIN model_versions mv ON mv.training_job_id = tj.id
            WHERE tj.id = $1::uuid
            """,
            job_id,
        )
        if not row:
            raise ValueError(f"training job not found: {job_id}")
        return training_job_payload(row)


async def fetch_dataset(conn: asyncpg.Connection, dataset_id: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        """
        SELECT
            id, name, description, task_type, language, status, total_items,
            created_by, owner_user_id, created_at, updated_at
        FROM dataset_versions
        WHERE id = $1::uuid
        """,
        dataset_id,
    )
    if not row:
        raise ValueError(f"dataset not found: {dataset_id}")
    return row


async def fetch_dataset_label_rows(conn: asyncpg.Connection, dataset_id: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            di.id AS item_id,
            di.event_id,
            di.text,
            di.split,
            di.cluster_id,
            di.auto_topic_label,
            di.reviewed_topic_label,
            dl.label_type,
            dl.label_value,
            dl.span_start,
            dl.span_end,
            al.broad_topic,
            al.storyline,
            al.sentiment,
            al.entities_json,
            al.quality
        FROM dataset_items di
        LEFT JOIN dataset_labels dl ON dl.dataset_item_id = di.id
        LEFT JOIN annotation_tasks at2 ON at2.dataset_item_id = di.id
        LEFT JOIN annotation_labels al ON al.task_id = at2.id
        WHERE di.dataset_version_id = $1::uuid
        """,
        dataset_id,
    )


async def latest_or_create_validation(
    conn: asyncpg.Connection,
    dataset_id: str,
    task_type: str,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT id, dataset_id, task_type, status, report_json, created_at
        FROM dataset_validation_reports
        WHERE dataset_id = $1::uuid AND task_type = $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        dataset_id,
        task_type,
    )
    if row:
        return dict(_json(row["report_json"]))
    dataset = await fetch_dataset(conn, dataset_id)
    rows = await fetch_dataset_label_rows(conn, dataset_id)
    report = validate_dataset_records(dict(dataset), [dict(r) for r in rows], task_type)
    await conn.execute(
        """
        INSERT INTO dataset_validation_reports (dataset_id, task_type, status, report_json)
        VALUES ($1::uuid, $2, $3, $4::jsonb)
        """,
        dataset_id,
        task_type,
        report["status"],
        json.dumps(report),
    )
    return report


async def register_candidate_model(
    conn: asyncpg.Connection,
    *,
    training_job_id: str,
    task_type: str,
    base_model: str,
    artifact_path: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    model_type = TASK_TO_MODEL_TYPE[task_type]
    version = f"{model_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{training_job_id[:8]}"
    model_name = f"{model_type}:{version}"
    baseline = await conn.fetchrow(
        """
        SELECT metrics_json
        FROM model_versions
        WHERE model_type=$1 AND status='deployed'
        ORDER BY deployed_at DESC
        LIMIT 1
        """,
        model_type,
    )
    primary_metric = metrics.get("primary_metric") or (
        "silhouette_after" if model_type == "embedding_model" else "macro_f1"
    )
    comparison = compare_to_baseline(
        metrics,
        _json(baseline["metrics_json"]) if baseline else None,
        primary_metric,
    )
    metrics_with_comparison = {
        **metrics,
        "comparison_to_baseline": comparison,
        "deployment_blocked": bool(comparison.get("deployment_warning")),
    }
    model_id = await conn.fetchval(
        """
        INSERT INTO model_versions (
            training_job_id, model_name, model_type, base_model, version,
            artifact_path, metrics_json, status
        )
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, 'candidate')
        RETURNING id
        """,
        training_job_id,
        model_name,
        model_type,
        base_model,
        version,
        artifact_path,
        json.dumps(metrics_with_comparison),
    )
    return {
        "id": str(model_id),
        "model_name": model_name,
        "model_type": model_type,
        "version": version,
        "artifact_path": artifact_path,
        "metrics": metrics_with_comparison,
        "status": "candidate",
    }


async def deploy_model(
    conn: asyncpg.Connection,
    *,
    model_id: str,
    consent_to_deploy: bool,
    actor_user_id: Optional[str],
    actor_role: Optional[str],
) -> dict[str, Any]:
    if consent_to_deploy is not True:
        raise ValueError("consent_to_deploy=true is required and no deployment was performed")
    if actor_role and actor_role not in {"admin", "ml_engineer", "owner"}:
        raise PermissionError("deploy requires admin, ml_engineer or owner role")
    actor_uuid = _uuid_or_none(actor_user_id) or uuid.UUID(int=0)
    model = await conn.fetchrow("SELECT * FROM model_versions WHERE id=$1::uuid", model_id)
    if not model:
        raise ValueError(f"model not found: {model_id}")
    if model["status"] not in {"candidate", "accepted", "deployed"}:
        raise ValueError(f"model status {model['status']} cannot be deployed")
    metrics = _json(model["metrics_json"])
    if metrics.get("deployment_blocked") is True:
        raise ValueError("candidate is worse than baseline on primary metric; deployment is blocked")
    previous = await conn.fetchrow(
        """
        SELECT id
        FROM model_versions
        WHERE model_type=$1 AND status='deployed' AND id<>$2::uuid
        ORDER BY deployed_at DESC
        LIMIT 1
        """,
        model["model_type"],
        model_id,
    )
    previous_id = str(previous["id"]) if previous else None
    request_id = await conn.fetchval(
        """
        INSERT INTO model_deployment_requests (
            model_version_id, requested_by, status, current_production_model_id,
            decision_by, decision_at
        )
        VALUES ($1::uuid, $2, 'deployed', $3::uuid, $2, NOW())
        RETURNING id
        """,
        model_id,
        actor_uuid,
        previous_id,
    )
    await conn.execute(
        """
        UPDATE model_versions
        SET status='archived'
        WHERE model_type=$1 AND status='deployed' AND id<>$2::uuid
        """,
        model["model_type"],
        model_id,
    )
    await conn.execute(
        """
        UPDATE model_versions
        SET status='deployed', deployed_at=NOW(), deployed_by=$2
        WHERE id=$1::uuid
        """,
        model_id,
        actor_uuid,
    )
    await conn.execute(
        """
        INSERT INTO model_deployment_history (
            model_version_id, previous_model_version_id, deployed_by, metadata_json
        )
        VALUES ($1::uuid, $2::uuid, $3, $4::jsonb)
        """,
        model_id,
        previous_id,
        actor_uuid,
        json.dumps({"request_id": str(request_id), "consent_to_deploy": True}),
    )
    row = await conn.fetchrow("SELECT * FROM model_versions WHERE id=$1::uuid", model_id)
    return model_payload(row)


def validation_report_payload(row: asyncpg.Record) -> dict[str, Any]:
    report = _json(row["report_json"])
    return {
        **report,
        "id": str(row["id"]),
        "dataset_id": str(row["dataset_id"]),
        "task_type": row["task_type"],
        "status": row["status"],
        "created_at": utc_iso(row["created_at"]),
    }


def training_job_payload(row: asyncpg.Record) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": str(data["id"]),
        "dataset_id": str(data["dataset_id"]),
        "dataset_name": data.get("dataset_name"),
        "task_type": data["task_type"],
        "base_model": data["base_model"],
        "training_config": _json(data["training_config_json"]),
        "status": data["status"],
        "consent_to_train_by": str(data["consent_to_train_by"]) if data["consent_to_train_by"] else None,
        "consent_to_train_at": utc_iso(data["consent_to_train_at"]),
        "started_at": utc_iso(data["started_at"]),
        "finished_at": utc_iso(data["finished_at"]),
        "error_message": data["error_message"],
        "created_at": utc_iso(data["created_at"]),
        "candidate_model": (
            {
                "id": str(data["model_version_id"]),
                "version": data["model_version"],
                "status": data["model_status"],
                "metrics": _json(data["model_metrics"]),
            }
            if data.get("model_version_id")
            else None
        ),
    }


def model_payload(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "training_job_id": str(row["training_job_id"]) if row["training_job_id"] else None,
        "model_name": row["model_name"],
        "model_type": row["model_type"],
        "base_model": row["base_model"],
        "version": row["version"],
        "artifact_path": row["artifact_path"],
        "metrics": _json(row["metrics_json"]),
        "status": row["status"],
        "created_at": utc_iso(row["created_at"]),
        "deployed_at": utc_iso(row["deployed_at"]),
        "deployed_by": str(row["deployed_by"]) if row["deployed_by"] else None,
    }
