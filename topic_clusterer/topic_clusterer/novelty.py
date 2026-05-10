from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


NOVELTY_ALGO_VERSION = "topic_novelty_v1"
NOVELTY_WEIGHTS: dict[str, float] = {
    "semantic_dissimilarity": 0.28,
    "entity_dissimilarity": 0.18,
    "channel_dissimilarity": 0.12,
    "keyword_dissimilarity": 0.12,
    "temporal_burst": 0.14,
    "sentiment_shift": 0.08,
    "new_entity_ratio": 0.08,
}


@dataclass(frozen=True)
class TopicSnapshot:
    public_cluster_id: str
    run_id: str
    cluster_id: int
    centroid: list[float]
    keywords: list[str]
    entities: dict[str, float]
    channels: dict[str, float]
    message_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    avg_sentiment: float


@dataclass(frozen=True)
class NoveltyResult:
    public_cluster_id: str
    novelty_score: float
    status: str
    nearest_topic_id: str | None
    features: dict[str, float]
    explanation: dict[str, Any]
    similarity_links: list[dict[str, Any]]


def calculate_topic_novelty(
    current: TopicSnapshot,
    history: list[TopicSnapshot],
    *,
    noise_probability_threshold: float = 0.0,
    cluster_probability: float | None = None,
) -> NoveltyResult:
    if cluster_probability is not None and cluster_probability <= noise_probability_threshold:
        return _result(current, 0.0, "noise", None, {}, [], ["Cluster probability is too low."])

    if not history:
        features = {
            "semantic_dissimilarity": 1.0,
            "entity_dissimilarity": 1.0,
            "channel_dissimilarity": 1.0,
            "keyword_dissimilarity": 1.0,
            "temporal_burst": _burst_score(current, None),
            "sentiment_shift": 0.0,
            "new_entity_ratio": 1.0 if current.entities else 0.0,
        }
        score = _weighted_score(features)
        return _result(
            current,
            score,
            "new" if score >= 0.55 else "uncertain",
            None,
            features,
            [],
            ["No previous topic history is available for comparison."],
        )

    links = [_similarity_link(current, old) for old in history]
    links.sort(key=lambda item: item["overall_similarity"], reverse=True)
    nearest = links[0]
    nearest_topic = next(t for t in history if t.public_cluster_id == nearest["topic_id"])
    known_entities = set().union(*(set(t.entities) for t in history))
    new_entities = sorted(set(current.entities) - known_entities)

    features = {
        "semantic_dissimilarity": 1.0 - nearest["semantic_similarity"],
        "entity_dissimilarity": 1.0 - nearest["entity_overlap"],
        "channel_dissimilarity": 1.0 - nearest["channel_overlap"],
        "keyword_dissimilarity": 1.0 - nearest["keyword_overlap"],
        "temporal_burst": _burst_score(current, history),
        "sentiment_shift": min(1.0, abs(current.avg_sentiment - nearest_topic.avg_sentiment) / 2.0),
        "new_entity_ratio": len(new_entities) / max(1, len(current.entities)),
    }
    score = _weighted_score(features)
    status = classify_novelty(score, nearest, current, history, nearest_topic)
    reasons = _reasons(features, score, nearest, new_entities)
    explanation = {
        "summary": _summary(status, score, nearest),
        "reasons": reasons,
        "nearest_topic_id": nearest["topic_id"],
        "new_entities": new_entities[:20],
        "formula": {
            "version": NOVELTY_ALGO_VERSION,
            "weights": NOVELTY_WEIGHTS,
        },
    }
    return NoveltyResult(
        public_cluster_id=current.public_cluster_id,
        novelty_score=score,
        status=status,
        nearest_topic_id=nearest["topic_id"],
        features={key: round(float(value), 6) for key, value in features.items()},
        explanation=explanation,
        similarity_links=links[:10],
    )


def classify_novelty(
    score: float,
    nearest: dict[str, Any],
    current: TopicSnapshot,
    history: list[TopicSnapshot],
    nearest_topic: TopicSnapshot | None = None,
) -> str:
    if current.message_count <= 1:
        return "uncertain"
    if score >= 0.68 and nearest["overall_similarity"] < 0.45:
        return "new"
    if nearest["overall_similarity"] >= 0.72 and score < 0.45:
        return "continuation"
    close_links = [
        link for link in (_similarity_link(current, old) for old in history)
        if link["overall_similarity"] >= 0.58
    ]
    if len(close_links) >= 2 and score < 0.6:
        return "merged"
    if nearest_topic is not None and nearest["overall_similarity"] >= 0.5 and _weighted_jaccard(current.entities, nearest_topic.entities) < 0.25:
        return "split"
    return "uncertain"


def _similarity_link(current: TopicSnapshot, old: TopicSnapshot) -> dict[str, Any]:
    semantic = _cosine(current.centroid, old.centroid)
    entity = _weighted_jaccard(current.entities, old.entities)
    channel = _weighted_jaccard(current.channels, old.channels)
    keyword = _set_jaccard(current.keywords, old.keywords)
    overall = 0.5 * semantic + 0.25 * entity + 0.15 * channel + 0.10 * keyword
    return {
        "topic_id": old.public_cluster_id,
        "run_id": old.run_id,
        "semantic_similarity": round(semantic, 6),
        "entity_overlap": round(entity, 6),
        "channel_overlap": round(channel, 6),
        "keyword_overlap": round(keyword, 6),
        "overall_similarity": round(overall, 6),
    }


def _weighted_score(features: dict[str, float]) -> float:
    return round(
        sum(features.get(name, 0.0) * weight for name, weight in NOVELTY_WEIGHTS.items()),
        6,
    )


def _burst_score(current: TopicSnapshot, history: list[TopicSnapshot] | None) -> float:
    current_hours = _duration_hours(current)
    current_rate = current.message_count / current_hours
    if not history:
        return min(1.0, math.log1p(current_rate) / math.log1p(20.0))
    historical_rates = [topic.message_count / _duration_hours(topic) for topic in history]
    baseline = float(np.median(historical_rates)) if historical_rates else 0.0
    if baseline <= 0:
        return min(1.0, current_rate / 10.0)
    return round(min(1.0, max(0.0, (current_rate / baseline - 1.0) / 4.0)), 6)


def _duration_hours(topic: TopicSnapshot) -> float:
    if topic.first_seen is None or topic.last_seen is None or topic.last_seen <= topic.first_seen:
        return 1.0
    return max(1.0, (topic.last_seen - topic.first_seen).total_seconds() / 3600.0)


def _weighted_jaccard(left: dict[str, float], right: dict[str, float]) -> float:
    if not left and not right:
        return 0.0
    keys = set(left) | set(right)
    numerator = sum(min(float(left.get(key, 0.0)), float(right.get(key, 0.0))) for key in keys)
    denominator = sum(max(float(left.get(key, 0.0)), float(right.get(key, 0.0))) for key in keys)
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _set_jaccard(left: list[str], right: list[str]) -> float:
    left_set = {item.lower() for item in left if item}
    right_set = {item.lower() for item in right if item}
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_arr = np.array(left, dtype=np.float32)
    right_arr = np.array(right, dtype=np.float32)
    denom = float(np.linalg.norm(left_arr) * np.linalg.norm(right_arr))
    if denom <= 0:
        return 0.0
    return max(0.0, min(1.0, float(left_arr @ right_arr / denom)))


def _reasons(
    features: dict[str, float],
    score: float,
    nearest: dict[str, Any],
    new_entities: list[str],
) -> list[str]:
    candidates = []
    if features["semantic_dissimilarity"] >= 0.55:
        candidates.append("Semantic vector is far from historical topics.")
    if features["entity_dissimilarity"] >= 0.6:
        candidates.append("Entity set barely overlaps with previous topics.")
    if features["new_entity_ratio"] >= 0.5 and new_entities:
        candidates.append("Most leading entities were not seen in topic history.")
    if features["temporal_burst"] >= 0.55:
        candidates.append("Message volume is growing faster than the historical baseline.")
    if features["sentiment_shift"] >= 0.35:
        candidates.append("Sentiment differs materially from the closest historical topic.")
    if not candidates:
        candidates.append("Signals are mixed; closest historical topic remains plausible.")
    candidates.append(f"Closest historical similarity is {nearest['overall_similarity']:.2f}; final novelty score is {score:.2f}.")
    return candidates


def _summary(status: str, score: float, nearest: dict[str, Any]) -> str:
    if status == "new":
        return f"Topic is likely new: novelty={score:.2f}, closest history={nearest['overall_similarity']:.2f}."
    if status == "continuation":
        return f"Topic likely continues an older topic: novelty={score:.2f}."
    return f"Topic novelty is {status}: novelty={score:.2f}."


def _result(
    current: TopicSnapshot,
    score: float,
    status: str,
    nearest_topic_id: str | None,
    features: dict[str, float],
    links: list[dict[str, Any]],
    reasons: list[str],
) -> NoveltyResult:
    return NoveltyResult(
        public_cluster_id=current.public_cluster_id,
        novelty_score=round(float(score), 6),
        status=status,
        nearest_topic_id=nearest_topic_id,
        features={key: round(float(value), 6) for key, value in features.items()},
        explanation={
            "summary": f"Topic novelty is {status}: novelty={score:.2f}.",
            "reasons": reasons,
            "nearest_topic_id": nearest_topic_id,
            "new_entities": sorted(current.entities)[:20],
            "formula": {"version": NOVELTY_ALGO_VERSION, "weights": NOVELTY_WEIGHTS},
        },
        similarity_links=links,
    )


def weighted_counts(items: list[dict[str, Any]], key_field: str, count_field: str = "count") -> dict[str, float]:
    counts: Counter[str] = Counter()
    for item in items:
        key = str(item.get(key_field) or item.get("id") or item.get("text") or "").strip().lower()
        if not key:
            continue
        counts[key] += float(item.get(count_field) or item.get("mention_count") or 1)
    return dict(counts)
