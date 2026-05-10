from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Any


ALGO_VERSION = "topic-comparison-v1"


@dataclass(frozen=True)
class TopicComparisonProfile:
    cluster_id: str
    label: str | None
    message_count: int
    first_seen: datetime | None
    last_seen: datetime | None
    avg_sentiment: float
    entities: dict[str, int]
    entity_labels: dict[str, dict[str, Any]]
    channels: dict[str, int]
    messages: list[dict[str, Any]]
    centroid: list[float] | None = None


def compare_topics(
    left: TopicComparisonProfile,
    right: TopicComparisonProfile,
) -> dict[str, Any]:
    if left.cluster_id == right.cluster_id:
        return _same_cluster_result(left, right)

    embedding_similarity = _cosine_similarity(left.centroid, right.centroid)
    entity_score = _weighted_jaccard(left.entities, right.entities)
    channel_score = _weighted_jaccard(left.channels, right.channels)
    time_metrics = _time_metrics(left.first_seen, left.last_seen, right.first_seen, right.last_seen)
    message_metrics = _message_metrics(left.messages, right.messages)
    sentiment_metrics = _sentiment_metrics(left.avg_sentiment, right.avg_sentiment)

    components = [
        ("embedding", embedding_similarity, 0.35, "centroid cosine similarity"),
        ("entities", entity_score, 0.25, "weighted entity overlap"),
        ("channels", channel_score, 0.12, "weighted channel overlap"),
        ("time", time_metrics["score"], 0.13, "time-window overlap and proximity"),
        ("messages", message_metrics["score"], 0.10, "representative message/fingerprint overlap"),
        ("sentiment", sentiment_metrics["score"], 0.05, "signed sentiment similarity"),
    ]
    available = [(name, score, weight, label) for name, score, weight, label in components if score is not None]
    weight_total = sum(weight for _, _, weight, _ in available) or 1.0
    breakdown = {
        name: {
            "score": round(float(score), 4),
            "weight": round(weight / weight_total, 4),
            "contribution": round((float(score) * weight) / weight_total, 4),
            "label": label,
        }
        for name, score, weight, label in available
    }
    similarity_score = round(sum(item["contribution"] for item in breakdown.values()), 4)
    classification = _classify(
        similarity_score,
        embedding_similarity,
        entity_score,
        channel_score,
        time_metrics["overlap_coefficient"],
        message_metrics["score"],
        sentiment_metrics["delta"],
    )

    shared_entities = _top_shared_items(left.entities, right.entities, left.entity_labels, limit=10)
    shared_channels = _top_shared_channels(left.channels, right.channels, limit=10)
    explanation = _build_explanation(
        classification,
        similarity_score,
        embedding_similarity,
        entity_score,
        channel_score,
        time_metrics,
        message_metrics,
        sentiment_metrics,
        shared_entities,
        shared_channels,
    )

    return {
        "cluster_a_id": left.cluster_id,
        "cluster_b_id": right.cluster_id,
        "algorithm_version": ALGO_VERSION,
        "similarity_score": similarity_score,
        "classification": classification,
        "is_same_topic": classification == "same_topic",
        "breakdown": breakdown,
        "evidence": {
            "entities": {
                "score": round(entity_score, 4),
                "shared": shared_entities,
                "a_count": len(left.entities),
                "b_count": len(right.entities),
            },
            "channels": {
                "score": round(channel_score, 4),
                "shared": shared_channels,
                "a_count": len(left.channels),
                "b_count": len(right.channels),
            },
            "time": time_metrics,
            "messages": message_metrics,
            "sentiment": sentiment_metrics,
            "embedding": {
                "score": None if embedding_similarity is None else round(embedding_similarity, 4),
                "available": embedding_similarity is not None,
            },
        },
        "topic_a": _topic_summary(left),
        "topic_b": _topic_summary(right),
        "explanation": explanation,
    }


def _same_cluster_result(
    left: TopicComparisonProfile,
    right: TopicComparisonProfile,
) -> dict[str, Any]:
    return {
        "cluster_a_id": left.cluster_id,
        "cluster_b_id": right.cluster_id,
        "algorithm_version": ALGO_VERSION,
        "similarity_score": 1.0,
        "classification": "same_topic",
        "is_same_topic": True,
        "breakdown": {
            "identity": {
                "score": 1.0,
                "weight": 1.0,
                "contribution": 1.0,
                "label": "same public_cluster_id",
            }
        },
        "evidence": {
            "entities": {"score": 1.0, "shared": [], "a_count": len(left.entities), "b_count": len(right.entities)},
            "channels": {"score": 1.0, "shared": [], "a_count": len(left.channels), "b_count": len(right.channels)},
            "time": _time_metrics(left.first_seen, left.last_seen, right.first_seen, right.last_seen),
            "messages": {"score": 1.0, "shared_event_ids": [], "shared_fingerprints": []},
            "sentiment": _sentiment_metrics(left.avg_sentiment, right.avg_sentiment),
            "embedding": {"score": 1.0, "available": left.centroid is not None and right.centroid is not None},
        },
        "topic_a": _topic_summary(left),
        "topic_b": _topic_summary(right),
        "explanation": {
            "summary": "Both ids point to the same cluster.",
            "positive_factors": ["Identical public_cluster_id."],
            "negative_factors": [],
            "subtopic_split_signals": [],
        },
    }


def _weighted_jaccard(left: dict[str, int], right: dict[str, int]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    numerator = sum(min(left.get(key, 0), right.get(key, 0)) for key in keys)
    denominator = sum(max(left.get(key, 0), right.get(key, 0)) for key in keys)
    return numerator / denominator if denominator else 0.0


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return None
    return max(0.0, min(1.0, (dot / (left_norm * right_norm) + 1.0) / 2.0))


def _time_metrics(
    left_start: datetime | None,
    left_end: datetime | None,
    right_start: datetime | None,
    right_end: datetime | None,
) -> dict[str, Any]:
    if not left_start or not left_end or not right_start or not right_end:
        return {
            "score": 0.0,
            "overlap_coefficient": 0.0,
            "overlap_seconds": 0.0,
            "gap_seconds": None,
        }
    left_seconds = max((left_end - left_start).total_seconds(), 1.0)
    right_seconds = max((right_end - right_start).total_seconds(), 1.0)
    overlap_seconds = max(
        0.0,
        (min(left_end, right_end) - max(left_start, right_start)).total_seconds(),
    )
    overlap_coefficient = overlap_seconds / max(1.0, min(left_seconds, right_seconds))
    if overlap_seconds > 0:
        gap_seconds = 0.0
        proximity = 1.0
    else:
        gap_seconds = min(
            abs((right_start - left_end).total_seconds()),
            abs((left_start - right_end).total_seconds()),
        )
        day = 24 * 60 * 60
        proximity = max(0.0, 1.0 - gap_seconds / (7 * day))
    score = max(overlap_coefficient, 0.35 * proximity)
    return {
        "score": round(score, 4),
        "overlap_coefficient": round(overlap_coefficient, 4),
        "overlap_seconds": round(overlap_seconds, 2),
        "gap_seconds": None if gap_seconds is None else round(gap_seconds, 2),
    }


def _message_metrics(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    left_event_ids = {item["event_id"] for item in left if item.get("event_id")}
    right_event_ids = {item["event_id"] for item in right if item.get("event_id")}
    shared_event_ids = sorted(left_event_ids & right_event_ids)

    left_fingerprints = _message_fingerprints(left)
    right_fingerprints = _message_fingerprints(right)
    shared_fingerprints = sorted(left_fingerprints & right_fingerprints)

    denominator = max(1, min(len(left_event_ids | left_fingerprints), len(right_event_ids | right_fingerprints)))
    score = min(1.0, (len(shared_event_ids) + len(shared_fingerprints)) / denominator)
    return {
        "score": round(score, 4),
        "shared_event_ids": shared_event_ids[:10],
        "shared_fingerprints": shared_fingerprints[:10],
    }


def _message_fingerprints(messages: list[dict[str, Any]]) -> set[str]:
    values: set[str] = set()
    for message in messages:
        for key in ("normalized_text_hash", "primary_url_fingerprint"):
            value = message.get(key)
            if value:
                values.add(f"{key}:{value}")
    return values


def _sentiment_metrics(left: float, right: float) -> dict[str, Any]:
    delta = abs(left - right)
    return {
        "score": round(max(0.0, 1.0 - min(delta / 2.0, 1.0)), 4),
        "delta": round(delta, 4),
        "a_avg_signed": round(left, 4),
        "b_avg_signed": round(right, 4),
    }


def _classify(
    score: float,
    embedding: float | None,
    entities: float,
    channels: float,
    time_overlap: float,
    messages: float,
    sentiment_delta: float,
) -> str:
    strong_semantic = (embedding is not None and embedding >= 0.86) or entities >= 0.5 or messages >= 0.35
    if score >= 0.74 and strong_semantic and time_overlap >= 0.25:
        return "same_topic"
    subtopic_signal = entities >= 0.42 and (channels < 0.35 or sentiment_delta >= 0.35 or time_overlap < 0.35)
    if score >= 0.48 and subtopic_signal:
        return "possible_subtopic_split"
    if score >= 0.45 or (entities >= 0.3 and time_overlap >= 0.25):
        return "related_topics"
    return "different_topics"


def _top_shared_items(
    left: dict[str, int],
    right: dict[str, int],
    labels: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    rows = []
    for key in set(left) & set(right):
        label = labels.get(key, {})
        rows.append(
            {
                "id": key,
                "text": label.get("text") or key,
                "type": label.get("type"),
                "a_mentions": left[key],
                "b_mentions": right[key],
                "min_mentions": min(left[key], right[key]),
            }
        )
    rows.sort(key=lambda item: (-item["min_mentions"], item["text"]))
    return rows[:limit]


def _top_shared_channels(left: dict[str, int], right: dict[str, int], limit: int) -> list[dict[str, Any]]:
    rows = [
        {
            "channel": channel,
            "a_count": left[channel],
            "b_count": right[channel],
            "min_count": min(left[channel], right[channel]),
        }
        for channel in set(left) & set(right)
    ]
    rows.sort(key=lambda item: (-item["min_count"], item["channel"]))
    return rows[:limit]


def _topic_summary(profile: TopicComparisonProfile) -> dict[str, Any]:
    return {
        "cluster_id": profile.cluster_id,
        "label": profile.label,
        "message_count": profile.message_count,
        "first_seen": _iso(profile.first_seen),
        "last_seen": _iso(profile.last_seen),
        "avg_sentiment": round(profile.avg_sentiment, 4),
        "entity_count": len(profile.entities),
        "channel_count": len(profile.channels),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _build_explanation(
    classification: str,
    score: float,
    embedding: float | None,
    entities: float,
    channels: float,
    time_metrics: dict[str, Any],
    message_metrics: dict[str, Any],
    sentiment_metrics: dict[str, Any],
    shared_entities: list[dict[str, Any]],
    shared_channels: list[dict[str, Any]],
) -> dict[str, Any]:
    positive: list[str] = []
    negative: list[str] = []
    subtopic: list[str] = []

    if embedding is None:
        negative.append("Embedding centroid similarity is unavailable in the analytics storage.")
    elif embedding >= 0.8:
        positive.append(f"Centroids are close ({embedding:.2f}).")
    elif embedding < 0.55:
        negative.append(f"Centroids are distant ({embedding:.2f}).")

    if entities >= 0.45:
        positive.append(f"Strong entity overlap ({entities:.2f}), led by {', '.join(item['text'] for item in shared_entities[:3])}.")
    elif entities >= 0.2:
        positive.append(f"Moderate entity overlap ({entities:.2f}).")
    else:
        negative.append("Entity overlap is weak.")

    if channels >= 0.35:
        positive.append(f"Topics are covered by overlapping channels ({channels:.2f}).")
    else:
        negative.append("Channel overlap is low.")

    if time_metrics["overlap_coefficient"] >= 0.5:
        positive.append("Topic activity windows substantially overlap.")
    elif time_metrics["gap_seconds"] == 0:
        positive.append("Topic activity windows overlap partially.")
    else:
        negative.append("Topic activity windows are separated in time.")

    if message_metrics["score"] > 0:
        positive.append("Representative messages or fingerprints intersect.")
    if sentiment_metrics["delta"] >= 0.35:
        negative.append(f"Average sentiment differs materially (delta {sentiment_metrics['delta']:.2f}).")
        subtopic.append("Different sentiment around shared actors can indicate a subtopic split.")
    if entities >= 0.42 and channels < 0.35:
        subtopic.append("Shared entities with different channel coverage can indicate parallel subtopics.")

    return {
        "summary": f"{classification} with similarity {score:.2f}.",
        "positive_factors": positive,
        "negative_factors": negative,
        "subtopic_split_signals": subtopic,
    }
