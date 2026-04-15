from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


QUOTE_PATTERN = re.compile(r"[\"'«»“”](.{20,240}?)[\"'«»“”]")


@dataclass(frozen=True)
class ResolutionMessage:
    event_id: str
    channel: str
    message_id: int
    message_date: datetime
    text: str
    normalized_text: str
    tokens: list[str]
    normalized_text_hash: Optional[str]
    simhash64: Optional[int]
    url_fingerprints: list[str]
    primary_url_fingerprint: Optional[str]
    entities: set[str]


@dataclass(frozen=True)
class ResolvedSource:
    source_type: str
    confidence: float
    source_event_id: Optional[str]
    source_channel: Optional[str]
    source_message_id: Optional[int]
    source_message_date: Optional[datetime]
    source_snippet: Optional[str]
    explanation: dict[str, Any]
    evidence: dict[str, Any]


def make_snippet(text: str, limit: int = 220) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def to_u64(value: int) -> int:
    return value & ((1 << 64) - 1)


def simhash_hamming_distance(left: Optional[int], right: Optional[int]) -> Optional[int]:
    if left is None or right is None:
        return None
    return (to_u64(left) ^ to_u64(right)).bit_count()


def jaccard_similarity(left: list[str], right: list[str]) -> float:
    left_set = {item for item in left if item}
    right_set = {item for item in right if item}
    if not left_set or not right_set:
        return 0.0
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def entity_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def quote_match_score(
    text: str,
    candidate_text: str,
    min_chars: int = 20,
) -> float:
    target = " ".join((text or "").lower().split())
    candidate = " ".join((candidate_text or "").lower().split())
    if not target or not candidate:
        return 0.0

    for match in QUOTE_PATTERN.findall(text or ""):
        fragment = " ".join(match.lower().split())
        if len(fragment) >= min_chars and fragment in candidate:
            return 1.0
    return 0.0


def unknown_source(reason: str) -> ResolvedSource:
    return ResolvedSource(
        source_type="unknown",
        confidence=0.0,
        source_event_id=None,
        source_channel=None,
        source_message_id=None,
        source_message_date=None,
        source_snippet=None,
        explanation={"summary": reason},
        evidence={"reason": reason},
    )


def build_inferred_source(
    target: ResolutionMessage,
    candidate: ResolutionMessage,
    threshold: float,
    quote_min_chars: int = 20,
) -> ResolvedSource:
    url_score = jaccard_similarity(target.url_fingerprints, candidate.url_fingerprints)
    entity_score = entity_overlap(target.entities, candidate.entities)
    lexical_score = jaccard_similarity(target.tokens, candidate.tokens)
    distance = simhash_hamming_distance(target.simhash64, candidate.simhash64)
    quote_score = quote_match_score(
        target.text,
        candidate.text,
        min_chars=quote_min_chars,
    )
    same_hash = (
        target.normalized_text_hash is not None
        and target.normalized_text_hash == candidate.normalized_text_hash
    )

    confidence = 0.0
    if same_hash:
        confidence += 0.45
    confidence += min(0.35, url_score * 0.35)
    confidence += min(0.2, entity_score * 0.2)
    confidence += min(0.2, lexical_score * 0.2)

    if distance is not None:
        if distance <= 3:
            confidence += 0.2
        elif distance <= 8:
            confidence += 0.12
        elif distance <= 16:
            confidence += 0.05

    delta_seconds = max(
        (target.message_date - candidate.message_date).total_seconds(),
        1.0,
    )
    confidence += min(0.05, 0.01 + (delta_seconds / 86400.0) * 0.01)
    confidence = min(confidence, 0.99)

    source_type = "quoted" if quote_score >= 1.0 else "inferred_semantic"
    explanation = {
        "summary": (
            "Quoted fragment matched an earlier message"
            if source_type == "quoted"
            else "Earlier message scored highest on shared textual and entity signals"
        ),
        "threshold": threshold,
    }
    evidence = {
        "same_normalized_text_hash": same_hash,
        "url_overlap": round(url_score, 4),
        "entity_overlap": round(entity_score, 4),
        "lexical_similarity": round(lexical_score, 4),
        "simhash_distance": distance,
        "quoted_fragment_match": quote_score >= 1.0,
        "earlier_seconds": round(delta_seconds, 3),
    }
    return ResolvedSource(
        source_type=source_type,
        confidence=confidence,
        source_event_id=candidate.event_id,
        source_channel=candidate.channel,
        source_message_id=candidate.message_id,
        source_message_date=candidate.message_date,
        source_snippet=make_snippet(candidate.text),
        explanation=explanation,
        evidence=evidence,
    )


def fallback_earliest_cluster_source(
    candidate: ResolutionMessage,
    confidence: float,
) -> ResolvedSource:
    return ResolvedSource(
        source_type="earliest_in_cluster",
        confidence=confidence,
        source_event_id=candidate.event_id,
        source_channel=candidate.channel,
        source_message_id=candidate.message_id,
        source_message_date=candidate.message_date,
        source_snippet=make_snippet(candidate.text),
        explanation={
            "summary": "Fell back to the earliest message currently assigned to the cluster"
        },
        evidence={"fallback": "earliest_in_cluster"},
    )
