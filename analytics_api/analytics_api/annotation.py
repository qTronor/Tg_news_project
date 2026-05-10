"""
Annotation module: SQL + pure data helpers for the dataset annotation system.
HTTP handlers are defined in service.py and call these functions.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

logger = logging.getLogger("analytics_api.annotation")

# ─── SQL ─────────────────────────────────────────────────────────────────────

SELECT_DATASETS_SQL = """
SELECT
    dv.id,
    dv.name,
    dv.description,
    dv.language,
    dv.window_start,
    dv.window_end,
    dv.channels,
    dv.min_word_count,
    dv.dedup_strategy,
    dv.total_items,
    dv.status,
    dv.config_json,
    dv.created_at,
    dv.updated_at,
    count(DISTINCT di.id) AS item_count,
    count(DISTINCT CASE WHEN at2.status = 'completed' THEN di.id END) AS annotated_count
FROM dataset_versions dv
LEFT JOIN dataset_items di ON di.dataset_version_id = dv.id
LEFT JOIN annotation_tasks at2 ON at2.dataset_item_id = di.id
WHERE dv.status != 'archived'
GROUP BY dv.id
ORDER BY dv.created_at DESC
LIMIT $1 OFFSET $2;
"""

SELECT_ANNOTATION_TASKS_SQL = """
SELECT
    at2.id,
    at2.status,
    at2.priority,
    at2.assigned_at,
    at2.started_at,
    at2.completed_at,
    at2.created_at,
    di.id AS item_id,
    di.event_id,
    di.channel,
    di.message_id,
    di.text,
    di.cleaned_text,
    di.message_date,
    di.word_count,
    di.language,
    di.split,
    di.cluster_id,
    di.auto_topic_label,
    dv.id AS dataset_version_id,
    dv.name AS dataset_version_name,
    ann.username AS annotator_username,
    al.broad_topic,
    al.storyline,
    al.is_new_storyline,
    al.quality,
    al.sentiment,
    al.entities_json,
    al.comment,
    al.annotator_confidence
FROM annotation_tasks at2
JOIN dataset_items di ON di.id = at2.dataset_item_id
JOIN dataset_versions dv ON dv.id = di.dataset_version_id
LEFT JOIN annotators ann ON ann.id = at2.annotator_id
LEFT JOIN annotation_labels al
    ON al.task_id = at2.id AND al.annotator_id = at2.annotator_id
WHERE ($1::text IS NULL OR at2.status = $1)
  AND ($2::uuid IS NULL OR dv.id = $2::uuid)
  AND ($3::uuid IS NULL OR at2.annotator_id = $3::uuid)
ORDER BY at2.priority DESC, at2.created_at ASC
LIMIT $4 OFFSET $5;
"""

SELECT_TASK_DETAIL_SQL = """
SELECT
    at2.id,
    at2.status,
    at2.priority,
    at2.assigned_at,
    at2.started_at,
    at2.completed_at,
    at2.created_at,
    di.id AS item_id,
    di.event_id,
    di.channel,
    di.message_id,
    di.text,
    di.cleaned_text,
    di.message_date,
    di.word_count,
    di.language,
    di.split,
    di.cluster_id,
    di.auto_topic_label,
    dv.name AS dataset_version_name,
    ann.username AS annotator_username,
    al.broad_topic,
    al.storyline,
    al.is_new_storyline,
    al.quality,
    al.sentiment,
    al.entities_json,
    al.comment,
    al.annotator_confidence
FROM annotation_tasks at2
JOIN dataset_items di ON di.id = at2.dataset_item_id
JOIN dataset_versions dv ON dv.id = di.dataset_version_id
LEFT JOIN annotators ann ON ann.id = at2.annotator_id
LEFT JOIN annotation_labels al
    ON al.task_id = at2.id AND al.annotator_id = at2.annotator_id
WHERE at2.id = $1;
"""

UPSERT_ANNOTATOR_SQL = """
INSERT INTO annotators (user_id, username)
VALUES ($1::uuid, $2)
ON CONFLICT (user_id) DO UPDATE SET
    username = EXCLUDED.username,
    updated_at = NOW()
RETURNING id;
"""

UPSERT_LABEL_SQL = """
INSERT INTO annotation_labels (
    task_id, annotator_id,
    broad_topic, broad_topic_confidence,
    storyline, is_new_storyline,
    quality, entities_json,
    sentiment, comment, annotator_confidence
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11)
ON CONFLICT (task_id, annotator_id) DO UPDATE SET
    broad_topic              = EXCLUDED.broad_topic,
    broad_topic_confidence   = EXCLUDED.broad_topic_confidence,
    storyline                = EXCLUDED.storyline,
    is_new_storyline         = EXCLUDED.is_new_storyline,
    quality                  = EXCLUDED.quality,
    entities_json            = EXCLUDED.entities_json,
    sentiment                = EXCLUDED.sentiment,
    comment                  = EXCLUDED.comment,
    annotator_confidence     = EXCLUDED.annotator_confidence,
    updated_at               = NOW()
RETURNING id;
"""

UPDATE_TASK_COMPLETE_SQL = """
UPDATE annotation_tasks
SET
    status       = 'completed',
    annotator_id = COALESCE(annotator_id, $2),
    started_at   = COALESCE(started_at, NOW()),
    completed_at = NOW()
WHERE id = $1;
"""

UPDATE_TASK_SKIP_SQL = """
UPDATE annotation_tasks
SET status = 'skipped', completed_at = NOW()
WHERE id = $1;
"""

INCREMENT_ANNOTATOR_COUNT_SQL = """
UPDATE annotators SET annotation_count = annotation_count + 1 WHERE id = $1;
"""

SELECT_ANNOTATION_STATS_SQL = """
SELECT
    dv.id   AS dataset_version_id,
    dv.name AS dataset_version_name,
    count(DISTINCT di.id)                                              AS total_items,
    count(DISTINCT CASE WHEN at2.status = 'completed' THEN di.id END) AS annotated_items,
    count(DISTINCT CASE WHEN at2.status = 'pending'   THEN di.id END) AS pending_items,
    count(DISTINCT CASE WHEN at2.status = 'skipped'   THEN di.id END) AS skipped_items,
    count(DISTINCT CASE WHEN al.quality = 'useful'    THEN al.id END) AS useful_count,
    count(DISTINCT CASE WHEN al.quality = 'noise'     THEN al.id END) AS noise_count,
    count(DISTINCT CASE WHEN al.quality = 'duplicate' THEN al.id END) AS duplicate_count,
    count(DISTINCT al.broad_topic) FILTER (WHERE al.broad_topic IS NOT NULL) AS distinct_topics
FROM dataset_versions dv
LEFT JOIN dataset_items di      ON di.dataset_version_id = dv.id
LEFT JOIN annotation_tasks at2  ON at2.dataset_item_id   = di.id
LEFT JOIN annotation_labels al  ON al.task_id            = at2.id
WHERE ($1::uuid IS NULL OR dv.id = $1::uuid)
GROUP BY dv.id, dv.name
ORDER BY dv.created_at DESC;
"""

SELECT_ACTIVE_GUIDELINES_SQL = """
SELECT id, version, title, content, created_at
FROM annotation_guidelines
WHERE is_active = TRUE
ORDER BY created_at DESC
LIMIT 1;
"""

INSERT_DATASET_SQL = """
INSERT INTO dataset_versions (
    name, description, language,
    window_start, window_end, channels,
    min_word_count, dedup_strategy, status, config_json, created_by
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'building', $9::jsonb, $10)
RETURNING id;
"""

INSERT_DATASET_ITEMS_SQL = """
INSERT INTO dataset_items (
    dataset_version_id, event_id, channel, message_id,
    text, cleaned_text, message_date, word_count, language, split, cluster_id,
    auto_topic_label, topic_label_source, topic_review_status, reviewed_topic_label
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
ON CONFLICT (dataset_version_id, event_id) DO NOTHING;
"""

SELECT_CANDIDATE_MESSAGES_SQL = """
SELECT
    pm.event_id,
    pm.channel,
    pm.message_id,
    rm.text,
    rm.message_date,
    pm.cleaned_text,
    pm.word_count,
    pm.original_language AS language,
    latest_cluster.public_cluster_id AS cluster_id,
    tl.label AS reviewed_topic_label,
    tl.source AS topic_label_source,
    tl.status AS topic_review_status
FROM preprocessed_messages pm
JOIN raw_messages rm ON rm.id = pm.raw_message_id
LEFT JOIN LATERAL (
    SELECT ca2.public_cluster_id
    FROM cluster_assignments ca2
    JOIN cluster_runs_pg cr ON cr.run_id = ca2.run_id
    WHERE ca2.event_id = pm.event_id
    ORDER BY cr.run_timestamp DESC
    LIMIT 1
) latest_cluster ON TRUE
LEFT JOIN topic_labels tl
    ON tl.public_cluster_id = latest_cluster.public_cluster_id
   AND tl.status IN ('active', 'noise', 'uncertain', 'rejected')
WHERE rm.message_date >= $1
  AND rm.message_date <= $2
  AND pm.word_count >= $3
  AND pm.original_language = ANY($4::text[])
  AND (cardinality($5::text[]) = 0 OR pm.channel = ANY($5::text[]))
ORDER BY rm.message_date ASC;
"""

FINALIZE_DATASET_SQL = """
UPDATE dataset_versions
SET status = 'ready', total_items = $1, updated_at = NOW()
WHERE id = $2;
"""

INSERT_SPLIT_SQL = """
INSERT INTO dataset_splits (dataset_version_id, split_name, item_count, ratio)
VALUES ($1, $2, $3, $4)
ON CONFLICT (dataset_version_id, split_name) DO UPDATE
SET item_count = EXCLUDED.item_count, ratio = EXCLUDED.ratio;
"""

SELECT_ANNOTATION_TOPICS_SQL = """
SELECT topic FROM (
    SELECT DISTINCT broad_topic AS topic FROM annotation_labels
    WHERE broad_topic IS NOT NULL AND broad_topic <> ''
    UNION
    SELECT DISTINCT storyline AS topic FROM annotation_labels
    WHERE storyline IS NOT NULL AND storyline <> ''
) t
ORDER BY topic ASC;
"""

FAIL_DATASET_SQL = """
UPDATE dataset_versions
SET status = 'archived', updated_at = NOW()
WHERE id = $1;
"""

EXPORT_ITEMS_SQL = """
SELECT
    di.event_id,
    di.channel,
    di.message_id,
    di.message_date,
    di.text,
    di.cleaned_text,
    di.word_count,
    di.language,
    di.split,
    di.cluster_id,
    di.auto_topic_label,
    di.topic_label_source,
    di.topic_review_status,
    di.reviewed_topic_label,
    al.broad_topic,
    al.storyline,
    al.is_new_storyline,
    al.quality,
    al.entities_json,
    al.comment,
    al.annotator_confidence,
    ann.username AS annotator
FROM dataset_items di
LEFT JOIN annotation_tasks at2
    ON at2.dataset_item_id = di.id AND at2.status = 'completed'
LEFT JOIN annotation_labels al ON al.task_id = at2.id
LEFT JOIN annotators ann ON ann.id = al.annotator_id
WHERE di.dataset_version_id = $1::uuid
ORDER BY di.split, di.message_date;
"""

# ─── Payload helpers ──────────────────────────────────────────────────────────

def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def task_payload(row: asyncpg.Record) -> dict[str, Any]:
    has_label = row.get("broad_topic") is not None or row.get("quality") is not None
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "priority": row["priority"],
        "assigned_at": _iso(row.get("assigned_at")),
        "started_at": _iso(row.get("started_at")),
        "completed_at": _iso(row.get("completed_at")),
        "created_at": _iso(row["created_at"]),
        "annotator_username": row.get("annotator_username"),
        "item": {
            "id": str(row["item_id"]),
            "event_id": row["event_id"],
            "channel": row["channel"],
            "message_id": row["message_id"],
            "text": row["text"],
            "cleaned_text": row.get("cleaned_text"),
            "message_date": _iso(row["message_date"]),
            "word_count": row["word_count"],
            "language": row.get("language"),
            "split": row["split"],
            "cluster_id": row.get("cluster_id"),
            "auto_topic_label": row.get("auto_topic_label"),
            "dataset_version_id": str(row["dataset_version_id"]) if row.get("dataset_version_id") else None,
            "dataset_version_name": row.get("dataset_version_name"),
        },
        "label": {
            "broad_topic": row.get("broad_topic"),
            "storyline": row.get("storyline"),
            "is_new_storyline": row.get("is_new_storyline"),
            "quality": row.get("quality") or "useful",
            "sentiment": row.get("sentiment"),
            "entities": row.get("entities_json") or [],
            "comment": row.get("comment"),
            "annotator_confidence": row.get("annotator_confidence"),
        } if has_label else None,
    }


def dataset_payload(row: asyncpg.Record) -> dict[str, Any]:
    total = int(row.get("item_count") or row.get("total_items") or 0)
    annotated = int(row.get("annotated_count") or 0)
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "description": row.get("description"),
        "language": row["language"],
        "window_start": _iso(row["window_start"]),
        "window_end": _iso(row["window_end"]),
        "channels": list(row.get("channels") or []),
        "min_word_count": row["min_word_count"],
        "dedup_strategy": row["dedup_strategy"],
        "total_items": total,
        "annotated_count": annotated,
        "annotation_progress": round(annotated / total, 3) if total > 0 else 0.0,
        "status": row["status"],
        "config": row.get("config_json") or {},
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row.get("updated_at")),
    }


# ─── Dataset builder (inline, called from the API build endpoint) ─────────────

import hashlib
import math
import uuid as _uuid


def _dedup(rows: list[asyncpg.Record], strategy: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if strategy == "event_id":
            key = row["event_id"]
        elif strategy == "text_hash":
            text = (row.get("cleaned_text") or row.get("text") or "").strip().lower()
            key = hashlib.sha256(text.encode()).hexdigest()
        else:
            key = str(_uuid.uuid4())
        if key not in seen:
            seen.add(key)
            out.append(dict(row))
    return out


def _assign_splits(
    items: list[dict],
    window_start: datetime,
    window_end: datetime,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.10,
    temporal_ratio: float = 0.05,
) -> list[dict]:
    if not items:
        return items

    window_secs = max((window_end - window_start).total_seconds(), 1.0)
    cutoff = window_start.replace(tzinfo=timezone.utc) + __import__("datetime").timedelta(
        seconds=window_secs * (1 - temporal_ratio)
    )

    def _tz(dt: datetime) -> datetime:
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    temporal = [i for i in items if _tz(i["message_date"]) >= cutoff]
    non_temp = [i for i in items if _tz(i["message_date"]) < cutoff]

    n = len(non_temp)
    denom = train_ratio + val_ratio + test_ratio
    n_train = math.floor(n * train_ratio / denom) if denom > 0 else n
    n_val   = math.floor(n * val_ratio   / denom) if denom > 0 else 0

    for i, item in enumerate(non_temp):
        if i < n_train:
            item["split"] = "train"
        elif i < n_train + n_val:
            item["split"] = "validation"
        else:
            item["split"] = "test"

    for item in temporal:
        item["split"] = "temporal_test"

    return non_temp + temporal


async def build_dataset(
    pool: asyncpg.Pool,
    name: str,
    description: str,
    window_start: datetime,
    window_end: datetime,
    channels: list[str],
    min_word_count: int = 5,
    dedup_strategy: str = "event_id",
    languages: list[str] | None = None,
    created_by: str | None = None,
) -> str:
    """Create a dataset_version, insert items and tasks. Returns version id."""
    langs = languages or ["ru", "en"]
    config = {
        "min_word_count": min_word_count,
        "dedup_strategy": dedup_strategy,
        "languages": langs,
        "splits": {"train": 0.70, "validation": 0.15, "test": 0.10, "temporal_test": 0.05},
    }

    async with pool.acquire() as conn:
        version_id = await conn.fetchval(
            INSERT_DATASET_SQL,
            name, description, "ru",
            window_start, window_end,
            channels or [],
            min_word_count, dedup_strategy,
            json.dumps(config),
            _uuid.UUID(created_by) if created_by else None,
        )

        try:
            rows = await conn.fetch(
                SELECT_CANDIDATE_MESSAGES_SQL,
                window_start, window_end,
                min_word_count, langs,
                channels or [],
            )
            items = _dedup(list(rows), dedup_strategy)
            items = _assign_splits(items, window_start, window_end)

            # Batch insert items
            records = [
                (
                    version_id,
                    item["event_id"],
                    item["channel"],
                    item["message_id"],
                    item["text"],
                    item.get("cleaned_text"),
                    item["message_date"],
                    item.get("word_count", 0),
                    item.get("language"),
                    item.get("split", "unassigned"),
                    item.get("cluster_id"),
                    item.get("reviewed_topic_label") or item.get("cluster_id"),
                    item.get("topic_label_source") or "auto",
                    item.get("topic_review_status"),
                    item.get("reviewed_topic_label"),
                )
                for item in items
            ]
            await conn.executemany(INSERT_DATASET_ITEMS_SQL, records)

            # Create one pending task per item
            item_ids = await conn.fetch(
                "SELECT id FROM dataset_items WHERE dataset_version_id = $1",
                version_id,
            )
            await conn.executemany(
                "INSERT INTO annotation_tasks (dataset_item_id, priority) VALUES ($1, 0)",
                [(r["id"],) for r in item_ids],
            )

            # Split stats
            split_counts: dict[str, int] = {}
            for item in items:
                split_counts[item.get("split", "unassigned")] = (
                    split_counts.get(item.get("split", "unassigned"), 0) + 1
                )
            total = len(items)
            for sname, cnt in split_counts.items():
                await conn.execute(
                    INSERT_SPLIT_SQL,
                    version_id, sname, cnt,
                    cnt / total if total > 0 else 0.0,
                )

            await conn.execute(FINALIZE_DATASET_SQL, total, version_id)
            logger.info("built dataset %s id=%s items=%d", name, version_id, total)

        except Exception:
            await conn.execute(FAIL_DATASET_SQL, version_id)
            logger.exception("build failed for dataset %s", name)
            raise

    return str(version_id)


# ─── Export ───────────────────────────────────────────────────────────────────

def _row_to_dict(row: dict) -> dict:
    return {
        "event_id": row.get("event_id"),
        "channel": row.get("channel"),
        "message_id": row.get("message_id"),
        "message_date": _iso(row.get("message_date")),
        "text": row.get("text"),
        "cleaned_text": row.get("cleaned_text"),
        "word_count": row.get("word_count"),
        "language": row.get("language"),
        "split": row.get("split"),
        "cluster_id": row.get("cluster_id"),
        "auto_topic_label": row.get("auto_topic_label"),
        "topic_label_source": row.get("topic_label_source") or "auto",
        "topic_review_status": row.get("topic_review_status"),
        "reviewed_topic_label": row.get("reviewed_topic_label"),
        "broad_topic": row.get("broad_topic"),
        "storyline": row.get("storyline"),
        "is_new_storyline": row.get("is_new_storyline"),
        "quality": row.get("quality"),
        "entities": row.get("entities_json") or [],
        "comment": row.get("comment"),
        "annotator_confidence": row.get("annotator_confidence"),
        "annotator": row.get("annotator"),
    }


async def export_dataset(
    conn: asyncpg.Connection,
    version_id: str,
    fmt: str,
) -> tuple[str, str, bytes]:
    """Returns (content_type, filename, content_bytes)."""
    dv = await conn.fetchrow(
        "SELECT name FROM dataset_versions WHERE id = $1::uuid", version_id
    )
    ds_name = dv["name"].replace(" ", "_") if dv else version_id

    rows = [dict(r) for r in await conn.fetch(EXPORT_ITEMS_SQL, version_id)]

    if fmt == "csv":
        return _export_csv(rows, ds_name)
    if fmt == "jsonl":
        return _export_jsonl(rows, ds_name)
    if fmt == "octis":
        return _export_octis(rows, ds_name)
    if fmt == "huggingface":
        return _export_huggingface(rows, ds_name)
    raise ValueError(f"unknown format: {fmt}")


_CSV_FIELDS = [
    "event_id", "channel", "message_id", "message_date", "text",
    "word_count", "language", "split", "cluster_id",
    "auto_topic_label", "topic_label_source", "topic_review_status", "reviewed_topic_label",
    "broad_topic", "storyline", "is_new_storyline", "quality",
    "entities", "comment", "annotator_confidence", "annotator",
]


def _export_csv(rows: list[dict], name: str) -> tuple[str, str, bytes]:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for row in rows:
        d = _row_to_dict(row)
        d["entities"] = json.dumps(d["entities"], ensure_ascii=False)
        w.writerow({k: (d.get(k) or "") for k in _CSV_FIELDS})
    return "text/csv", f"{name}.csv", buf.getvalue().encode("utf-8")


def _export_jsonl(rows: list[dict], name: str) -> tuple[str, str, bytes]:
    lines = [json.dumps(_row_to_dict(r), ensure_ascii=False) for r in rows]
    return "application/jsonl", f"{name}.jsonl", "\n".join(lines).encode("utf-8")


def _export_octis(rows: list[dict], name: str) -> tuple[str, str, bytes]:
    corpus, meta = [], ["event_id\tchannel\tmessage_date\tsplit\tbroad_topic\tquality"]
    for row in rows:
        text = ((row.get("cleaned_text") or row.get("text")) or "").replace("\n", " ").replace("\t", " ")
        corpus.append(text)
        meta.append("\t".join([
            row.get("event_id") or "",
            row.get("channel") or "",
            _iso(row.get("message_date")) or "",
            row.get("split") or "",
            row.get("broad_topic") or "",
            row.get("quality") or "",
        ]))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("corpus.tsv", "\n".join(corpus))
        z.writestr("metadata.tsv", "\n".join(meta))
    return "application/zip", f"{name}_octis.zip", buf.getvalue()


def _export_huggingface(rows: list[dict], name: str) -> tuple[str, str, bytes]:
    splits: dict[str, list] = {}
    for row in rows:
        splits.setdefault(row.get("split") or "unassigned", []).append(_row_to_dict(row))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for sname, items in splits.items():
            z.writestr(f"{sname}.jsonl", "\n".join(json.dumps(i, ensure_ascii=False) for i in items))
        card_lines = [f"# {name}\n", "Telegram news topic modeling dataset.\n", "## Splits\n"]
        for sname, items in splits.items():
            card_lines.append(f"- **{sname}**: {len(items)} items")
        z.writestr("README.md", "\n".join(card_lines))
    return "application/zip", f"{name}_hf.zip", buf.getvalue()
