from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from topic_clusterer.novelty import TopicSnapshot, calculate_topic_novelty  # noqa: E402


def _snapshot(
    cluster_id: str,
    centroid: list[float],
    entities: dict[str, float],
    channels: dict[str, float],
    keywords: list[str],
    message_count: int = 20,
    sentiment: float = 0.0,
) -> TopicSnapshot:
    return TopicSnapshot(
        public_cluster_id=cluster_id,
        run_id=cluster_id.split(":", 1)[0],
        cluster_id=int(cluster_id.rsplit(":", 1)[1]),
        centroid=centroid,
        keywords=keywords,
        entities=entities,
        channels=channels,
        message_count=message_count,
        first_seen=datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc),
        last_seen=datetime(2026, 5, 3, 11, 0, tzinfo=timezone.utc),
        avg_sentiment=sentiment,
    )


def test_synthetic_unrelated_topic_is_new() -> None:
    old = _snapshot(
        "run_old:0",
        [1.0, 0.0, 0.0],
        {"org:central bank": 8},
        {"banksta": 10},
        ["rate", "central bank"],
    )
    current = _snapshot(
        "run_new:0",
        [0.0, 1.0, 0.0],
        {"person:new minister": 6, "org:new agency": 5},
        {"rbc_news": 20},
        ["minister", "resignation"],
        message_count=40,
    )

    result = calculate_topic_novelty(current, [old])

    assert result.status == "new"
    assert result.novelty_score >= 0.68
    assert result.features["semantic_dissimilarity"] > 0.9
    assert "org:new agency" in result.explanation["new_entities"]


def test_similar_topic_is_continuation() -> None:
    old = _snapshot(
        "run_old:0",
        [1.0, 0.0, 0.0],
        {"org:central bank": 10, "person:nabiullina": 3},
        {"banksta": 12, "rbc_news": 4},
        ["rate", "central bank", "inflation"],
    )
    current = _snapshot(
        "run_new:0",
        [0.98, 0.02, 0.0],
        {"org:central bank": 9, "person:nabiullina": 2},
        {"banksta": 8, "rbc_news": 3},
        ["rate", "central bank", "inflation"],
    )

    result = calculate_topic_novelty(current, [old])

    assert result.status == "continuation"
    assert result.novelty_score < 0.45
    assert result.nearest_topic_id == "run_old:0"


def test_similar_semantics_with_new_entities_is_split_or_uncertain() -> None:
    old = _snapshot(
        "run_old:0",
        [1.0, 0.0],
        {"org:central bank": 10, "org:minfin": 5},
        {"banksta": 10},
        ["budget", "rate"],
    )
    current = _snapshot(
        "run_new:0",
        [0.9, 0.1],
        {"org:new bank": 8, "person:new ceo": 6},
        {"banksta": 8},
        ["budget", "bank"],
    )

    result = calculate_topic_novelty(current, [old])

    assert result.status in {"split", "uncertain", "new"}
    assert result.features["new_entity_ratio"] == 1.0


def test_single_message_false_positive_is_uncertain() -> None:
    old = _snapshot("run_old:0", [1.0, 0.0], {"org:a": 5}, {"c1": 5}, ["a"], 10)
    current = _snapshot("run_new:0", [0.0, 1.0], {"org:b": 1}, {"c2": 1}, ["b"], 1)

    result = calculate_topic_novelty(current, [old])

    assert result.status == "uncertain"
