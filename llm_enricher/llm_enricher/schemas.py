from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Input DTO ────────────────────────────────────────────────────────────────

class RepresentativeMessage(BaseModel):
    text: str
    channel: str
    posted_at: Optional[str] = None
    cluster_probability: float = 0.0


class TopEntity(BaseModel):
    normalized_text: str
    entity_type: str
    mention_count: int


class SentimentSummary(BaseModel):
    positive_prob: float = 0.0
    negative_prob: float = 0.0
    neutral_prob: float = 0.0
    dominant_emotion: Optional[str] = None


class TimelineBucket(BaseModel):
    bucket_start: str
    bucket_end: str
    message_count: int
    unique_channel_count: int
    top_entities: list[dict[str, Any]] = Field(default_factory=list)
    sentiment: dict[str, Any] = Field(default_factory=dict)
    new_channels: list[str] = Field(default_factory=list)


class EvolutionEvent(BaseModel):
    event_type: str
    severity: float
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class GraphTopNode(BaseModel):
    node_label: str
    node_type: str
    pagerank: float = 0.0
    bridge_score: float = 0.0
    is_bridge: bool = False


class ClusterEnrichmentInput(BaseModel):
    public_cluster_id: str
    language: str = "und"
    analysis_mode: str = "unknown"
    label: Optional[str] = None
    importance_score: Optional[float] = None
    importance_level: Optional[str] = None
    score_breakdown: Optional[dict[str, Any]] = None
    features: Optional[dict[str, Any]] = None
    representative_messages: list[RepresentativeMessage] = Field(default_factory=list)
    top_entities: list[TopEntity] = Field(default_factory=list)
    sentiment_summary: Optional[SentimentSummary] = None
    timeline_buckets: list[TimelineBucket] = Field(default_factory=list)
    evolution_events: list[EvolutionEvent] = Field(default_factory=list)
    graph_top_nodes: list[GraphTopNode] = Field(default_factory=list)
    graph_community_summary: Optional[dict[str, Any]] = None
    graph_subgraph_metrics: Optional[dict[str, Any]] = None


# ── Output JSON schemas (jsonschema Draft-7) ──────────────────────────────────

CLUSTER_SUMMARY_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["summary", "key_points"],
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "maxLength": 1200},
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
    },
}

CLUSTER_EXPLANATION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["why_important", "drivers"],
    "additionalProperties": False,
    "properties": {
        "why_important": {"type": "string"},
        "drivers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "weight", "explanation"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "weight": {"type": "number"},
                    "explanation": {"type": "string"},
                },
            },
            "maxItems": 5,
        },
    },
}

NOVELTY_EXPLANATION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["novelty_verdict", "rationale"],
    "additionalProperties": False,
    "properties": {
        "novelty_verdict": {
            "type": "string",
            "enum": ["new", "ongoing", "resurgent"],
        },
        "rationale": {"type": "string"},
    },
}

CLUSTER_LABEL_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["label", "confidence"],
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "maxLength": 160},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "cluster_summary": CLUSTER_SUMMARY_SCHEMA,
    "cluster_explanation": CLUSTER_EXPLANATION_SCHEMA,
    "novelty_explanation": NOVELTY_EXPLANATION_SCHEMA,
    "cluster_label": CLUSTER_LABEL_SCHEMA,
}

SUPPORTED_ENRICHMENT_TYPES = frozenset(OUTPUT_SCHEMAS.keys())

MAX_TOKENS: dict[str, int] = {
    "cluster_summary": 500,
    "cluster_explanation": 600,
    "novelty_explanation": 300,
    "cluster_label": 100,
}
