from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from topic_clusterer.novelty import (  # noqa: E402
    NOVELTY_ALGO_VERSION,
    TopicSnapshot,
    calculate_topic_novelty,
    weighted_counts,
)


SIGNED_SENTIMENT_SQL = """
CASE
    WHEN sr.positive_prob IS NOT NULL OR sr.negative_prob IS NOT NULL
        THEN COALESCE(sr.positive_prob, 0) - COALESCE(sr.negative_prob, 0)
    WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'positive'
        THEN COALESCE(sr.sentiment_score, 0)
    WHEN lower(COALESCE(sr.sentiment_label, 'neutral')) = 'negative'
        THEN -COALESCE(sr.sentiment_score, 0)
    ELSE 0
END
"""


SELECT_TOPIC_SNAPSHOTS_SQL = f"""
SELECT
    tcm.public_cluster_id,
    tcm.run_id,
    tcm.cluster_id,
    tcm.centroid_json,
    tcm.keywords_json,
    tcm.top_channels_json,
    min(rm.message_date) AS first_seen,
    max(rm.message_date) AS last_seen,
    count(ca.event_id) AS message_count,
    count(DISTINCT rm.channel) AS channel_count,
    COALESCE(avg({SIGNED_SENTIMENT_SQL}), 0) AS avg_sentiment
FROM topic_cluster_metadata tcm
JOIN cluster_assignments ca ON ca.public_cluster_id = tcm.public_cluster_id
JOIN raw_messages rm ON rm.event_id = ca.event_id
LEFT JOIN sentiment_results sr ON sr.event_id = ca.event_id
WHERE ca.cluster_id >= 0
GROUP BY
    tcm.public_cluster_id,
    tcm.run_id,
    tcm.cluster_id,
    tcm.centroid_json,
    tcm.keywords_json,
    tcm.top_channels_json
ORDER BY first_seen ASC NULLS LAST, tcm.run_id ASC, tcm.cluster_id ASC;
"""


SELECT_ENTITIES_SQL = """
SELECT
    ca.public_cluster_id,
    lower(COALESCE(nr.normalized_text, nr.entity_text)) AS entity_key,
    COALESCE(max(nr.normalized_text), min(nr.entity_text)) AS entity_text,
    nr.entity_type,
    count(*) AS mention_count
FROM cluster_assignments ca
JOIN ner_results nr ON nr.event_id = ca.event_id
WHERE ca.public_cluster_id = ANY($1::varchar[])
  AND ca.cluster_id >= 0
GROUP BY ca.public_cluster_id, lower(COALESCE(nr.normalized_text, nr.entity_text)), nr.entity_type
ORDER BY ca.public_cluster_id, mention_count DESC, entity_text ASC;
"""


UPSERT_TOPIC_HISTORY_SQL = """
INSERT INTO topic_history (
    public_cluster_id, run_id, cluster_id, first_seen, last_seen, message_count,
    channel_count, avg_sentiment, centroid_json, keywords_json, entities_json,
    channels_json, metadata_json, updated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb, $13::jsonb, NOW())
ON CONFLICT (public_cluster_id) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    cluster_id = EXCLUDED.cluster_id,
    first_seen = EXCLUDED.first_seen,
    last_seen = EXCLUDED.last_seen,
    message_count = EXCLUDED.message_count,
    channel_count = EXCLUDED.channel_count,
    avg_sentiment = EXCLUDED.avg_sentiment,
    centroid_json = EXCLUDED.centroid_json,
    keywords_json = EXCLUDED.keywords_json,
    entities_json = EXCLUDED.entities_json,
    channels_json = EXCLUDED.channels_json,
    metadata_json = EXCLUDED.metadata_json,
    updated_at = EXCLUDED.updated_at;
"""


INSERT_TOPIC_NOVELTY_SCORE_SQL = """
INSERT INTO topic_novelty_scores (
    public_cluster_id, run_id, novelty_score, novelty_status, nearest_topic_id,
    features_json, explanation_json, algorithm_version, calculated_at
)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, NOW());
"""


INSERT_TOPIC_LIFECYCLE_EVENT_SQL = """
INSERT INTO topic_lifecycle_events (
    public_cluster_id, run_id, event_type, event_time, related_topic_id, confidence, details_json
)
VALUES ($1, $2, $3, NOW(), $4, $5, $6::jsonb);
"""


UPSERT_TOPIC_SIMILARITY_LINK_SQL = """
INSERT INTO topic_similarity_links (
    source_cluster_id, target_cluster_id, run_id, semantic_similarity,
    entity_overlap, channel_overlap, keyword_overlap, overall_similarity,
    evidence_json, calculated_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
ON CONFLICT (source_cluster_id, target_cluster_id) DO UPDATE SET
    run_id = EXCLUDED.run_id,
    semantic_similarity = EXCLUDED.semantic_similarity,
    entity_overlap = EXCLUDED.entity_overlap,
    channel_overlap = EXCLUDED.channel_overlap,
    keyword_overlap = EXCLUDED.keyword_overlap,
    overall_similarity = EXCLUDED.overall_similarity,
    evidence_json = EXCLUDED.evidence_json,
    calculated_at = EXCLUDED.calculated_at;
"""


def json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def float_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        try:
            out[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill topic novelty scores from topic_cluster_metadata.")
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--clear", action="store_true", help="Delete previous novelty rows before recalculation.")
    args = parser.parse_args()
    if not args.dsn:
        raise SystemExit("DATABASE_URL or --dsn is required")

    conn = await asyncpg.connect(args.dsn)
    try:
        rows = await conn.fetch(SELECT_TOPIC_SNAPSHOTS_SQL)
        cluster_ids = [row["public_cluster_id"] for row in rows]
        entity_rows = await conn.fetch(SELECT_ENTITIES_SQL, cluster_ids) if cluster_ids else []
        entities_by_cluster: dict[str, list[dict[str, Any]]] = {}
        for row in entity_rows:
            entities_by_cluster.setdefault(row["public_cluster_id"], []).append(
                {
                    "id": f"{row['entity_type']}:{row['entity_key']}",
                    "text": row["entity_text"],
                    "type": row["entity_type"],
                    "mention_count": int(row["mention_count"] or 0),
                }
            )

        if args.clear and cluster_ids:
            await conn.execute("DELETE FROM topic_similarity_links WHERE source_cluster_id = ANY($1::varchar[]);", cluster_ids)
            await conn.execute(
                "DELETE FROM topic_lifecycle_events WHERE public_cluster_id = ANY($1::varchar[]) AND details_json ? 'features';",
                cluster_ids,
            )
            await conn.execute(
                "DELETE FROM topic_novelty_scores WHERE public_cluster_id = ANY($1::varchar[]) AND algorithm_version = $2;",
                cluster_ids,
                NOVELTY_ALGO_VERSION,
            )

        history: list[TopicSnapshot] = []
        scored = 0
        async with conn.transaction():
            for row in rows:
                current = TopicSnapshot(
                    public_cluster_id=row["public_cluster_id"],
                    run_id=row["run_id"],
                    cluster_id=int(row["cluster_id"]),
                    centroid=[float(v) for v in json_value(row["centroid_json"], [])],
                    keywords=[str(v) for v in json_value(row["keywords_json"], [])],
                    entities=weighted_counts(entities_by_cluster.get(row["public_cluster_id"], []), "id", "mention_count"),
                    channels=weighted_counts(json_value(row["top_channels_json"], []), "channel", "count"),
                    message_count=int(row["message_count"] or 0),
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    avg_sentiment=float(row["avg_sentiment"] or 0),
                )
                await conn.execute(
                    UPSERT_TOPIC_HISTORY_SQL,
                    current.public_cluster_id,
                    current.run_id,
                    current.cluster_id,
                    current.first_seen,
                    current.last_seen,
                    current.message_count,
                    int(row["channel_count"] or 0),
                    current.avg_sentiment,
                    json.dumps(current.centroid),
                    json.dumps(current.keywords, ensure_ascii=False),
                    json.dumps(current.entities, ensure_ascii=False),
                    json.dumps(current.channels, ensure_ascii=False),
                    json.dumps({"backfill": True, "algorithm_version": NOVELTY_ALGO_VERSION}),
                )
                result = calculate_topic_novelty(current, history)
                await conn.execute(
                    INSERT_TOPIC_NOVELTY_SCORE_SQL,
                    result.public_cluster_id,
                    current.run_id,
                    result.novelty_score,
                    result.status,
                    result.nearest_topic_id,
                    json.dumps(result.features, ensure_ascii=False),
                    json.dumps(result.explanation, ensure_ascii=False),
                    NOVELTY_ALGO_VERSION,
                )
                await conn.execute(
                    INSERT_TOPIC_LIFECYCLE_EVENT_SQL,
                    result.public_cluster_id,
                    current.run_id,
                    result.status,
                    result.nearest_topic_id,
                    result.novelty_score,
                    json.dumps({"features": result.features, "explanation": result.explanation}, ensure_ascii=False),
                )
                for link in result.similarity_links:
                    await conn.execute(
                        UPSERT_TOPIC_SIMILARITY_LINK_SQL,
                        result.public_cluster_id,
                        link["topic_id"],
                        current.run_id,
                        link["semantic_similarity"],
                        link["entity_overlap"],
                        link["channel_overlap"],
                        link["keyword_overlap"],
                        link["overall_similarity"],
                        json.dumps(link, ensure_ascii=False),
                    )
                history.append(current)
                scored += 1
        print(json.dumps({"topics_scored": scored}, ensure_ascii=False))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
