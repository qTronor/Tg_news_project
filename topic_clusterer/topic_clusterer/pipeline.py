from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional, Protocol

import numpy as np


TOKEN_RE = re.compile(r"(?u)\b[\w-]{3,}\b")


@dataclass(frozen=True)
class CorpusItem:
    event_id: str
    channel: str
    message_id: int
    text: str
    embedding: np.ndarray
    timestamp: datetime
    bucket_id: str


@dataclass(frozen=True)
class TopicMetadata:
    cluster_id: int
    centroid: list[float]
    keywords: list[str]
    representative_messages: list[dict[str, Any]]
    top_channels: list[dict[str, Any]]
    time_distribution: list[dict[str, Any]]
    confidence_score: float
    stability_score: float


@dataclass(frozen=True)
class PipelineResult:
    labels: np.ndarray
    probabilities: np.ndarray
    strategy: str
    reduced_embeddings: Optional[np.ndarray]
    topic_metadata: dict[int, TopicMetadata]
    metrics: dict[str, Any]


class CorpusLoader:
    def from_rows(self, rows: Iterable[Any], parse_timestamp) -> list[CorpusItem]:
        items: list[CorpusItem] = []
        for row in rows:
            ts = parse_timestamp(row["event_timestamp"] if isinstance(row, dict) else row[6])
            embedding_raw = row["embedding"] if isinstance(row, dict) else row[4]
            embedding = np.array(json.loads(embedding_raw or "[]"), dtype=np.float32)
            items.append(
                CorpusItem(
                    event_id=row["event_id"] if isinstance(row, dict) else row[0],
                    channel=row["channel"] if isinstance(row, dict) else row[1],
                    message_id=int(row["message_id"] if isinstance(row, dict) else row[2]),
                    text=row["text"] if isinstance(row, dict) else row[3],
                    embedding=embedding,
                    timestamp=ts,
                    bucket_id=row["bucket_id"] if isinstance(row, dict) else row[5],
                )
            )
        return items


class EmbeddingBuilder:
    def build(self, items: list[CorpusItem]) -> np.ndarray:
        if not items:
            return np.empty((0, 0), dtype=np.float32)
        return np.vstack([item.embedding for item in items]).astype(np.float32)


class DimensionalityReducer:
    def __init__(self, *, n_neighbors: int, n_components: int, min_dist: float, seed: int) -> None:
        self.n_neighbors = n_neighbors
        self.n_components = n_components
        self.min_dist = min_dist
        self.seed = seed

    def reduce(self, embeddings: np.ndarray) -> np.ndarray:
        if len(embeddings) <= 2:
            return embeddings
        n_neighbors = min(self.n_neighbors, len(embeddings) - 1)
        if n_neighbors < 2:
            return embeddings
        import umap

        reducer = umap.UMAP(
            n_components=max(2, min(self.n_components, len(embeddings) - 2)),
            metric="cosine",
            n_neighbors=n_neighbors,
            min_dist=self.min_dist,
            random_state=self.seed,
        )
        return reducer.fit_transform(embeddings)


class Clusterer:
    def __init__(
        self,
        *,
        min_cluster_size: int,
        min_samples: int,
        fallback_similarity_threshold: float,
        min_topic_size: Optional[int] = None,
    ) -> None:
        self.min_cluster_size = min_topic_size or min_cluster_size
        self.min_samples = min_samples
        self.fallback_similarity_threshold = fallback_similarity_threshold

    def cluster(self, embeddings: np.ndarray, reduced: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
        if len(embeddings) < self.min_cluster_size:
            labels, probs = self._fallback_cluster(embeddings)
            return labels, probs, "similarity_fallback"
        import hdbscan

        model = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            cluster_selection_method="leaf",
            allow_single_cluster=False,
            prediction_data=True,
        )
        model.fit(reduced)
        labels = model.labels_.astype(int)
        probs = model.probabilities_.astype(float)
        n_clusters = len(set(labels.tolist())) - (1 if -1 in labels else 0)
        if n_clusters <= 0:
            labels, probs = self._fallback_cluster(embeddings)
            return labels, probs, "similarity_fallback"
        return labels, probs, "umap_hdbscan"

    def _fallback_cluster(self, embeddings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if len(embeddings) == 0:
            return np.array([], dtype=int), np.array([], dtype=float)
        if len(embeddings) == 1:
            return np.array([0], dtype=int), np.array([1.0], dtype=float)
        normalized = normalize_embeddings(embeddings)
        parent = list(range(len(normalized)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        similarity = normalized @ normalized.T
        for left in range(len(normalized)):
            for right in range(left + 1, len(normalized)):
                if float(similarity[left, right]) >= self.fallback_similarity_threshold:
                    union(left, right)

        root_to_label: dict[int, int] = {}
        labels = np.full(len(normalized), -1, dtype=int)
        for index in range(len(normalized)):
            root = find(index)
            root_to_label.setdefault(root, len(root_to_label))
            labels[index] = root_to_label[root]

        probs = np.ones(len(normalized), dtype=float)
        for label in set(labels.tolist()):
            members = np.where(labels == label)[0]
            centroid = normalize_vector(normalized[members].mean(axis=0))
            probs[members] = np.clip(normalized[members] @ centroid, 0.55, 0.99)
        return labels, probs


class TopicRepresenter:
    def __init__(self, *, top_n_words: int, ngram_range: tuple[int, int]) -> None:
        self.top_n_words = top_n_words
        self.ngram_range = ngram_range

    def represent(
        self,
        items: list[CorpusItem],
        embeddings: np.ndarray,
        labels: np.ndarray,
        probabilities: np.ndarray,
    ) -> dict[int, TopicMetadata]:
        metadata: dict[int, TopicMetadata] = {}
        normalized = normalize_embeddings(embeddings) if len(embeddings) else embeddings
        for label in sorted({int(v) for v in labels.tolist() if int(v) >= 0}):
            idx = np.where(labels == label)[0]
            centroid = normalize_vector(normalized[idx].mean(axis=0))
            scores = normalized[idx] @ centroid
            ranked_positions = idx[np.argsort(-scores)[:5]]
            topic_items = [items[i] for i in idx]
            metadata[label] = TopicMetadata(
                cluster_id=label,
                centroid=centroid.astype(float).round(6).tolist(),
                keywords=self._keywords([item.text for item in topic_items]),
                representative_messages=[
                    {
                        "event_id": items[i].event_id,
                        "channel": items[i].channel,
                        "message_id": items[i].message_id,
                        "score": round(float(scores[list(idx).index(i)]), 6),
                    }
                    for i in ranked_positions
                ],
                top_channels=[
                    {"channel": channel, "count": count}
                    for channel, count in Counter(item.channel for item in topic_items).most_common(10)
                ],
                time_distribution=[
                    {"bucket_id": bucket, "count": count}
                    for bucket, count in sorted(Counter(item.bucket_id for item in topic_items).items())
                ],
                confidence_score=round(float(np.mean(probabilities[idx])), 6),
                stability_score=round(float(np.clip(np.mean(scores), 0.0, 1.0)), 6),
            )
        return metadata

    def _keywords(self, texts: list[str]) -> list[str]:
        doc_tokens = [_ngrams(_tokens(text), self.ngram_range) for text in texts]
        term_counts = Counter(term for terms in doc_tokens for term in terms)
        doc_freq = Counter(term for terms in doc_tokens for term in set(terms))
        total_docs = max(1, len(texts))
        scored = []
        for term, count in term_counts.items():
            idf = math.log((1 + total_docs) / (1 + doc_freq[term])) + 1
            scored.append((term, count * idf))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [term for term, _ in scored[: self.top_n_words]]


class OutlierHandler:
    def reassign(self, embeddings: np.ndarray, labels: np.ndarray, probabilities: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if -1 not in labels:
            return labels, probabilities
        valid_labels = sorted({int(v) for v in labels.tolist() if int(v) >= 0})
        if not valid_labels:
            return labels, probabilities
        normalized = normalize_embeddings(embeddings)
        centroids = {label: normalize_vector(normalized[labels == label].mean(axis=0)) for label in valid_labels}
        for index in np.where(labels == -1)[0]:
            best_label, best_score = max(
                ((label, float(normalized[index] @ centroid)) for label, centroid in centroids.items()),
                key=lambda item: item[1],
            )
            if best_score >= 0.62:
                labels[index] = best_label
                probabilities[index] = min(0.8, max(0.55, best_score))
        return labels, probabilities


class TopicMerger:
    def __init__(self, nr_topics: Optional[int]) -> None:
        self.nr_topics = nr_topics

    def merge(self, embeddings: np.ndarray, labels: np.ndarray, probabilities: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if not self.nr_topics:
            return labels, probabilities
        valid_labels = sorted({int(v) for v in labels.tolist() if int(v) >= 0})
        if len(valid_labels) <= self.nr_topics:
            return labels, probabilities
        normalized = normalize_embeddings(embeddings)
        sizes = {label: int((labels == label).sum()) for label in valid_labels}
        while len(valid_labels) > self.nr_topics:
            smallest = min(valid_labels, key=lambda label: sizes[label])
            centroid = normalize_vector(normalized[labels == smallest].mean(axis=0))
            candidates = [label for label in valid_labels if label != smallest]
            target = max(
                candidates,
                key=lambda label: float(centroid @ normalize_vector(normalized[labels == label].mean(axis=0))),
            )
            labels[labels == smallest] = target
            valid_labels.remove(smallest)
            sizes[target] += sizes[smallest]
        remap = {label: i for i, label in enumerate(sorted(valid_labels))}
        for old, new in remap.items():
            labels[labels == old] = new
        return labels, probabilities


class ResultPersister(Protocol):
    def persist(self, result: PipelineResult) -> None:
        ...


class TopicModelingPipeline:
    def __init__(
        self,
        *,
        reducer: DimensionalityReducer,
        clusterer: Clusterer,
        representer: TopicRepresenter,
        outlier_handler: OutlierHandler,
        topic_merger: TopicMerger,
    ) -> None:
        self.reducer = reducer
        self.clusterer = clusterer
        self.representer = representer
        self.outlier_handler = outlier_handler
        self.topic_merger = topic_merger

    def run(self, items: list[CorpusItem]) -> PipelineResult:
        embeddings = EmbeddingBuilder().build(items)
        if len(items) == 0:
            return PipelineResult(np.array([], dtype=int), np.array([], dtype=float), "empty", None, {}, {})
        reduced = self.reducer.reduce(embeddings)
        labels, probabilities, strategy = self.clusterer.cluster(embeddings, reduced)
        labels, probabilities = self.outlier_handler.reassign(embeddings, labels, probabilities)
        labels, probabilities = self.topic_merger.merge(embeddings, labels, probabilities)
        topic_metadata = self.representer.represent(items, embeddings, labels, probabilities)
        n_clusters = len(topic_metadata)
        metrics = {
            "n_clusters": n_clusters,
            "noise_ratio": round(float((labels == -1).sum() / max(1, len(labels))), 6),
            "mean_probability": round(float(np.mean(probabilities)) if len(probabilities) else 0.0, 6),
            "mean_stability": round(float(np.mean([m.stability_score for m in topic_metadata.values()])) if topic_metadata else 0.0, 6),
        }
        return PipelineResult(labels, probabilities, strategy, reduced, topic_metadata, metrics)


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return embeddings / norms


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def _ngrams(tokens: list[str], ngram_range: tuple[int, int]) -> list[str]:
    min_n, max_n = ngram_range
    terms: list[str] = []
    for n in range(max(1, min_n), max_n + 1):
        for i in range(0, max(0, len(tokens) - n + 1)):
            terms.append(" ".join(tokens[i : i + n]))
    return terms
