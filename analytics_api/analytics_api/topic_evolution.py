from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional


SUPPORTED_BUCKET_SIZES = {"15m", "1h", "1d"}
ACTOR_ENTITY_TYPES = {"PERSON", "PER", "ORG"}


@dataclass(frozen=True)
class TopicMessage:
    event_id: str
    channel: str
    message_date: datetime
    sentiment_label: str = "neutral"
    signed_sentiment: float = 0.0


@dataclass(frozen=True)
class TopicEntity:
    event_id: str
    entity_key: str
    entity_text: str
    entity_type: str
    mention_count: int = 1


@dataclass
class TimelinePoint:
    bucket_start: datetime
    bucket_end: datetime
    message_count: int
    unique_channel_count: int
    top_entities: list[dict[str, Any]]
    sentiment: dict[str, Any]
    new_channels: list[str]
    event_ids: list[str] = field(default_factory=list)


@dataclass
class EvolutionEvent:
    event_type: str
    event_time: datetime
    bucket_start: datetime
    severity: float
    summary: str
    details: dict[str, Any]


def normalize_bucket_size(value: Optional[str]) -> str:
    bucket_size = (value or "1h").lower()
    if bucket_size not in SUPPORTED_BUCKET_SIZES:
        raise ValueError("bucket must be one of: 15m, 1h, 1d")
    return bucket_size


def floor_bucket(value: datetime, bucket_size: str) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    bucket_size = normalize_bucket_size(bucket_size)
    if bucket_size == "15m":
        minute = value.minute - (value.minute % 15)
        return value.replace(minute=minute, second=0, microsecond=0)
    if bucket_size == "1h":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_delta(bucket_size: str) -> timedelta:
    bucket_size = normalize_bucket_size(bucket_size)
    if bucket_size == "15m":
        return timedelta(minutes=15)
    if bucket_size == "1h":
        return timedelta(hours=1)
    return timedelta(days=1)


def build_timeline_points(
    messages: Iterable[TopicMessage],
    entities_by_event: dict[str, list[TopicEntity]],
    bucket_size: str,
) -> list[TimelinePoint]:
    bucket_size = normalize_bucket_size(bucket_size)
    step = bucket_delta(bucket_size)
    grouped: dict[datetime, list[TopicMessage]] = defaultdict(list)
    for message in messages:
        grouped[floor_bucket(message.message_date, bucket_size)].append(message)

    seen_channels: set[str] = set()
    points: list[TimelinePoint] = []
    for bucket_start in sorted(grouped):
        bucket_messages = sorted(grouped[bucket_start], key=lambda item: item.message_date)
        event_ids = [message.event_id for message in bucket_messages]
        channels = {message.channel for message in bucket_messages}
        new_channels = sorted(channels - seen_channels)
        seen_channels.update(channels)

        sentiment_counts = Counter(
            (message.sentiment_label or "neutral").lower() for message in bucket_messages
        )
        signed_values = [message.signed_sentiment for message in bucket_messages]
        entity_counter: Counter[tuple[str, str, str]] = Counter()
        for event_id in event_ids:
            for entity in entities_by_event.get(event_id, []):
                key = (
                    entity.entity_key.lower(),
                    entity.entity_text,
                    entity.entity_type.upper(),
                )
                entity_counter[key] += max(1, int(entity.mention_count or 1))

        top_entities = [
            {
                "id": f"{entity_type}:{entity_key}",
                "text": entity_text,
                "type": entity_type,
                "mention_count": count,
            }
            for (entity_key, entity_text, entity_type), count in entity_counter.most_common(10)
        ]

        total = len(bucket_messages)
        sentiment = {
            "positive": int(sentiment_counts["positive"]),
            "neutral": int(sentiment_counts["neutral"]),
            "negative": int(sentiment_counts["negative"]),
            "avg_signed": round(sum(signed_values) / total, 4) if total else 0.0,
        }
        points.append(
            TimelinePoint(
                bucket_start=bucket_start,
                bucket_end=bucket_start + step,
                message_count=total,
                unique_channel_count=len(channels),
                top_entities=top_entities,
                sentiment=sentiment,
                new_channels=new_channels,
                event_ids=event_ids,
            )
        )
    return points


def detect_evolution_events(points: list[TimelinePoint]) -> list[EvolutionEvent]:
    if not points:
        return []

    events: list[EvolutionEvent] = [
        EvolutionEvent(
            event_type="topic_created",
            event_time=points[0].bucket_start,
            bucket_start=points[0].bucket_start,
            severity=1.0,
            summary="First message in topic timeline",
            details={
                "message_count": points[0].message_count,
                "channels": points[0].new_channels,
            },
        )
    ]

    seen_entities: set[str] = set()
    previous_sentiment: Optional[float] = None
    previous_counts: deque[int] = deque(maxlen=3)
    peak_count = points[0].message_count

    for index, point in enumerate(points):
        if index > 0 and point.new_channels:
            events.append(
                EvolutionEvent(
                    event_type="new_channel_joined",
                    event_time=point.bucket_start,
                    bucket_start=point.bucket_start,
                    severity=min(1.0, 0.4 + len(point.new_channels) * 0.2),
                    summary="New channel joined topic",
                    details={"channels": point.new_channels},
                )
            )

        current_actor_keys: list[str] = []
        for entity in point.top_entities:
            entity_type = str(entity.get("type") or "").upper()
            entity_id = str(entity.get("id") or "")
            if entity_type in ACTOR_ENTITY_TYPES and entity_id and entity_id not in seen_entities:
                current_actor_keys.append(entity_id)
            if entity_id:
                seen_entities.add(entity_id)
        if index > 0 and current_actor_keys:
            events.append(
                EvolutionEvent(
                    event_type="new_actor_detected",
                    event_time=point.bucket_start,
                    bucket_start=point.bucket_start,
                    severity=min(1.0, 0.35 + len(current_actor_keys) * 0.15),
                    summary="New actor/entity detected",
                    details={"entity_ids": current_actor_keys[:10]},
                )
            )

        current_sentiment = float(point.sentiment.get("avg_signed", 0.0))
        if previous_sentiment is not None:
            sentiment_delta = current_sentiment - previous_sentiment
            if abs(sentiment_delta) >= 0.35:
                events.append(
                    EvolutionEvent(
                        event_type="sentiment_shift",
                        event_time=point.bucket_start,
                        bucket_start=point.bucket_start,
                        severity=min(1.0, abs(sentiment_delta)),
                        summary="Topic sentiment shifted",
                        details={
                            "previous_avg_signed": previous_sentiment,
                            "current_avg_signed": current_sentiment,
                            "delta": round(sentiment_delta, 4),
                        },
                    )
                )
        previous_sentiment = current_sentiment

        if previous_counts:
            baseline = sum(previous_counts) / len(previous_counts)
            if baseline > 0 and point.message_count >= max(3, baseline * 2):
                events.append(
                    EvolutionEvent(
                        event_type="growth_spike",
                        event_time=point.bucket_start,
                        bucket_start=point.bucket_start,
                        severity=min(1.0, point.message_count / max(1.0, baseline * 4)),
                        summary="Message volume growth spike",
                        details={
                            "message_count": point.message_count,
                            "baseline_message_count": round(baseline, 2),
                        },
                    )
                )
            if peak_count >= 3 and point.message_count <= max(1, int(baseline * 0.5)):
                events.append(
                    EvolutionEvent(
                        event_type="decline_started",
                        event_time=point.bucket_start,
                        bucket_start=point.bucket_start,
                        severity=min(1.0, (baseline - point.message_count) / max(1.0, baseline)),
                        summary="Topic volume decline started",
                        details={
                            "message_count": point.message_count,
                            "baseline_message_count": round(baseline, 2),
                            "peak_message_count": peak_count,
                        },
                    )
                )

        previous_counts.append(point.message_count)
        peak_count = max(peak_count, point.message_count)

    return _dedupe_events(events)


def _dedupe_events(events: list[EvolutionEvent]) -> list[EvolutionEvent]:
    deduped: list[EvolutionEvent] = []
    seen: set[tuple[str, datetime, str]] = set()
    for event in events:
        key = (event.event_type, event.bucket_start, event.summary)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped
