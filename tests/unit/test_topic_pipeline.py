from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from topic_clusterer.pipeline import (  # noqa: E402
    Clusterer,
    CorpusItem,
    EmbeddingBuilder,
    OutlierHandler,
    TopicMerger,
    TopicRepresenter,
    config_hash,
)


def _item(event_id: str, text: str, embedding: list[float], channel: str = "c1") -> CorpusItem:
    return CorpusItem(
        event_id=event_id,
        channel=channel,
        message_id=int(event_id.rsplit(":", 1)[1]),
        text=text,
        embedding=np.array(embedding, dtype=np.float32),
        timestamp=datetime(2026, 5, 2, tzinfo=timezone.utc),
        bucket_id="2026-05-02T00:00:00+00:00",
    )


def test_embedding_builder_preserves_precomputed_vectors() -> None:
    items = [
        _item("c1:1", "банк повысил ставку", [1.0, 0.0]),
        _item("c1:2", "рынок акций вырос", [0.0, 1.0]),
    ]

    embeddings = EmbeddingBuilder().build(items)

    assert embeddings.shape == (2, 2)
    assert embeddings.dtype == np.float32


def test_clusterer_fallback_groups_similar_short_messages() -> None:
    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.98, 0.02],
            [0.0, 1.0],
            [0.02, 0.98],
        ],
        dtype=np.float32,
    )

    labels, probabilities, strategy = Clusterer(
        min_cluster_size=10,
        min_samples=2,
        fallback_similarity_threshold=0.9,
    ).cluster(embeddings, embeddings)

    assert strategy == "similarity_fallback"
    assert len(set(labels.tolist())) == 2
    assert probabilities.min() >= 0.55


def test_topic_representer_outputs_keywords_and_exemplars() -> None:
    items = [
        _item("c1:1", "центробанк повысил ключевую ставку", [1.0, 0.0]),
        _item("c1:2", "банк повысил ставку по кредитам", [0.98, 0.02], "c2"),
    ]
    embeddings = EmbeddingBuilder().build(items)
    labels = np.array([0, 0], dtype=int)
    probabilities = np.array([0.9, 0.8], dtype=float)

    metadata = TopicRepresenter(top_n_words=5, ngram_range=(1, 2)).represent(
        items,
        embeddings,
        labels,
        probabilities,
    )

    topic = metadata[0]
    assert "ставку" in topic.keywords
    assert topic.representative_messages[0]["event_id"] in {"c1:1", "c1:2"}
    assert topic.top_channels == [{"channel": "c1", "count": 1}, {"channel": "c2", "count": 1}]
    assert 0 < topic.confidence_score <= 1


def test_outlier_handler_and_topic_merger_are_deterministic() -> None:
    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.99, 0.01],
            [0.0, 1.0],
            [0.01, 0.99],
            [0.95, 0.05],
        ],
        dtype=np.float32,
    )
    labels = np.array([0, 0, 1, 1, -1], dtype=int)
    probabilities = np.array([0.9, 0.9, 0.8, 0.8, 0.0], dtype=float)

    reassigned, probs = OutlierHandler().reassign(embeddings, labels, probabilities)
    merged, _ = TopicMerger(nr_topics=1).merge(embeddings, reassigned, probs)

    assert reassigned[4] == 0
    assert set(merged.tolist()) == {0}


def test_config_hash_is_stable_for_reordered_dicts() -> None:
    assert config_hash({"b": 2, "a": 1}) == config_hash({"a": 1, "b": 2})
