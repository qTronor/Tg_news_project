"""SQL and payload helpers for human review of topic clusters."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import asyncpg

REVIEW_REASONS = {
    "new_topic",
    "low_confidence",
    "high_outlier_ratio",
    "history_conflict",
    "rapid_growth",
    "manual_request",
}

REVIEW_ACTIONS = {"confirm", "rename", "merge", "split", "reject"}
LABEL_SOURCES = {"auto", "human", "merged", "split"}

SELECT_REVIEW_CANDIDATES_SQL = """
WITH latest_run AS (
    SELECT run_id, total_messages, total_noise
    FROM cluster_runs_pg
    ORDER BY run_timestamp DESC
    LIMIT 1
),
cluster_stats AS (
    SELECT
        ca.public_cluster_id,
        ca.run_id,
        count(*) AS message_count,
        min(rm.message_date) AS first_seen,
        max(rm.message_date) AS last_seen,
        count(*) FILTER (
            WHERE rm.message_date >= NOW() - INTERVAL '24 hours'
        ) AS recent_count,
        count(*) FILTER (
            WHERE rm.message_date < NOW() - INTERVAL '24 hours'
              AND rm.message_date >= NOW() - INTERVAL '48 hours'
        ) AS previous_count
    FROM cluster_assignments ca
    JOIN latest_run lr ON lr.run_id = ca.run_id
    JOIN raw_messages rm ON rm.event_id = ca.event_id
    WHERE ca.cluster_id >= 0
    GROUP BY ca.public_cluster_id, ca.run_id
)
SELECT
    cs.public_cluster_id,
    cs.run_id,
    cs.message_count,
    cs.first_seen,
    cs.last_seen,
    cs.recent_count,
    cs.previous_count,
    lr.total_messages,
    lr.total_noise,
    tcm.confidence_score,
    tcm.stability_score,
    tcm.keywords_json,
    tcm.top_entities_json,
    tl.label AS active_label,
    tl.source AS active_label_source
FROM cluster_stats cs
JOIN latest_run lr ON lr.run_id = cs.run_id
LEFT JOIN topic_cluster_metadata tcm ON tcm.public_cluster_id = cs.public_cluster_id
LEFT JOIN topic_labels tl
    ON tl.public_cluster_id = cs.public_cluster_id
   AND tl.status = 'active'
ORDER BY cs.message_count DESC, cs.last_seen DESC;
"""

INSERT_REVIEW_TASK_SQL = """
INSERT INTO topic_review_tasks (
    public_cluster_id, run_id, reason, status, priority, signals_json, requested_by
) VALUES ($1, $2, $3, 'pending', $4, $5::jsonb, $6)
ON CONFLICT (public_cluster_id, reason) WHERE status IN ('pending', 'in_progress', 'deferred')
DO UPDATE SET
    priority = GREATEST(topic_review_tasks.priority, EXCLUDED.priority),
    signals_json = topic_review_tasks.signals_json || EXCLUDED.signals_json,
    updated_at = NOW()
RETURNING id;
"""

SELECT_REVIEW_TASKS_SQL = """
SELECT
    trt.id,
    trt.public_cluster_id,
    trt.run_id,
    trt.reason,
    trt.status,
    trt.priority,
    trt.signals_json,
    trt.requested_by,
    trt.assigned_to,
    trt.created_at,
    trt.updated_at,
    trt.completed_at,
    tl.label AS active_label,
    tl.source AS label_source,
    tl.status AS label_status
FROM topic_review_tasks trt
LEFT JOIN topic_labels tl
    ON tl.public_cluster_id = trt.public_cluster_id
   AND tl.status = 'active'
WHERE ($1::text IS NULL OR trt.status = $1)
  AND ($2::varchar IS NULL OR trt.public_cluster_id = $2)
ORDER BY trt.priority DESC, trt.created_at ASC
LIMIT $3 OFFSET $4;
"""

SELECT_REVIEW_TASK_SQL = """
SELECT
    trt.id,
    trt.public_cluster_id,
    trt.run_id,
    trt.reason,
    trt.status,
    trt.priority,
    trt.signals_json,
    trt.requested_by,
    trt.assigned_to,
    trt.created_at,
    trt.updated_at,
    trt.completed_at,
    tl.id AS active_label_id,
    tl.label AS active_label,
    tl.description AS active_description,
    tl.source AS label_source,
    tl.status AS label_status
FROM topic_review_tasks trt
LEFT JOIN topic_labels tl
    ON tl.public_cluster_id = trt.public_cluster_id
   AND tl.status = 'active'
WHERE trt.id = $1::uuid;
"""

SELECT_ACTIVE_LABEL_SQL = """
SELECT id, public_cluster_id, run_id, label, description, status, source, confidence, metadata_json
FROM topic_labels
WHERE public_cluster_id = $1 AND status = 'active'
LIMIT 1;
"""

SUPERSEDE_ACTIVE_LABEL_SQL = """
UPDATE topic_labels
SET status = 'superseded'
WHERE public_cluster_id = $1 AND status = 'active'
RETURNING id;
"""

INSERT_TOPIC_LABEL_SQL = """
INSERT INTO topic_labels (
    public_cluster_id, run_id, label, description, status, source, confidence, created_by, metadata_json
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
RETURNING id;
"""

UPDATE_TASK_DONE_SQL = """
UPDATE topic_review_tasks
SET status = $2, completed_at = NOW(), updated_at = NOW()
WHERE id = $1::uuid;
"""

INSERT_REVIEW_ACTION_SQL = """
INSERT INTO topic_review_actions (
    task_id, public_cluster_id, action, actor_user_id, actor_username,
    old_value, new_value, comment
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
RETURNING id;
"""

INSERT_MERGE_HISTORY_SQL = """
INSERT INTO topic_merge_history (
    source_cluster_id, target_cluster_id, resulting_label_id, action_id,
    reason, actor_user_id, metadata_json
) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
RETURNING id;
"""

INSERT_SPLIT_HISTORY_SQL = """
INSERT INTO topic_split_history (
    source_cluster_id, child_labels_json, event_ids_json, action_id,
    reason, actor_user_id, metadata_json
) VALUES ($1, $2::jsonb, $3::jsonb, $4, $5, $6, $7::jsonb)
RETURNING id;
"""

SELECT_REVIEW_ACTIONS_SQL = """
SELECT
    id,
    task_id,
    public_cluster_id,
    action,
    actor_user_id,
    actor_username,
    old_value,
    new_value,
    comment,
    created_at
FROM topic_review_actions
WHERE public_cluster_id = $1
ORDER BY created_at DESC
LIMIT $2;
"""


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso(value)
    return str(value)


def clamp_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return max(0.0, min(1.0, float(value)))


def review_reasons_for_candidate(row: asyncpg.Record | dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    confidence = row.get("confidence_score")
    stability = row.get("stability_score")
    total = int(row.get("total_messages") or 0)
    noise = int(row.get("total_noise") or 0)
    outlier_ratio = noise / total if total > 0 else 0.0
    recent = int(row.get("recent_count") or 0)
    previous = int(row.get("previous_count") or 0)
    active_label = row.get("active_label")
    active_source = row.get("active_label_source")

    reasons: list[tuple[str, int, dict[str, Any]]] = []
    if not active_label:
        reasons.append(("new_topic", 60, {"active_label": None}))
    if confidence is not None and float(confidence) < 0.55:
        reasons.append(("low_confidence", 80, {"confidence_score": float(confidence)}))
    if stability is not None and float(stability) < 0.50:
        reasons.append(("low_confidence", 75, {"stability_score": float(stability)}))
    if outlier_ratio >= 0.35:
        reasons.append(("high_outlier_ratio", 70, {"outlier_ratio": round(outlier_ratio, 4)}))
    if recent >= 5 and (previous == 0 or recent / max(previous, 1) >= 2.0):
        reasons.append(("rapid_growth", 65, {"recent_count": recent, "previous_count": previous}))
    if active_label and active_source == "auto" and confidence is not None and float(confidence) < 0.65:
        reasons.append(
            (
                "history_conflict",
                68,
                {"active_label": active_label, "label_source": active_source, "confidence_score": float(confidence)},
            )
        )
    return reasons


def task_payload(row: asyncpg.Record, topic: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "cluster_id": row["public_cluster_id"],
        "run_id": row.get("run_id"),
        "reason": row["reason"],
        "status": row["status"],
        "priority": int(row["priority"] or 0),
        "signals": json_value(row.get("signals_json"), {}),
        "requested_by": str(row["requested_by"]) if row.get("requested_by") else None,
        "assigned_to": str(row["assigned_to"]) if row.get("assigned_to") else None,
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row.get("updated_at")),
        "completed_at": iso(row.get("completed_at")),
        "active_label": row.get("active_label"),
        "label_source": row.get("label_source"),
        "label_status": row.get("label_status"),
        "topic": topic,
    }


def action_payload(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "cluster_id": row["public_cluster_id"],
        "action": row["action"],
        "actor_user_id": str(row["actor_user_id"]) if row.get("actor_user_id") else None,
        "actor_username": row.get("actor_username"),
        "old_value": row.get("old_value"),
        "new_value": row.get("new_value"),
        "comment": row.get("comment"),
        "created_at": iso(row["created_at"]),
    }


def json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value
