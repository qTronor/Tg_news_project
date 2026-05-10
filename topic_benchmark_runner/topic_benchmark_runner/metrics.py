from __future__ import annotations

import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(token) >= 3 and not token.isdigit()
    ]


def topic_diversity(topic_words: list[list[str]], top_k: int = 10) -> float:
    selected = [word for words in topic_words for word in words[:top_k]]
    if not selected:
        return 0.0
    return len(set(selected)) / len(selected)


def umass_coherence(documents: list[list[str]], topic_words: list[list[str]], top_k: int = 10) -> float:
    if not documents or not topic_words:
        return 0.0
    doc_sets = [set(doc) for doc in documents]
    doc_freq = Counter(word for doc in doc_sets for word in doc)
    pair_freq: dict[tuple[str, str], int] = defaultdict(int)
    for doc in doc_sets:
        for left, right in combinations(sorted(doc), 2):
            pair_freq[(left, right)] += 1

    scores: list[float] = []
    for words in topic_words:
        selected = words[:top_k]
        for i in range(1, len(selected)):
            for j in range(i):
                wi = selected[i]
                wj = selected[j]
                pair = tuple(sorted((wi, wj)))
                numerator = pair_freq.get(pair, 0) + 1
                denominator = doc_freq.get(wj, 0) + 1
                scores.append(math.log(numerator / denominator))
    return float(sum(scores) / len(scores)) if scores else 0.0


def outlier_ratio(labels: list[int]) -> float:
    if not labels:
        return 0.0
    return sum(1 for label in labels if label == -1) / len(labels)


def cluster_count(labels: list[int]) -> int:
    return len({label for label in labels if label >= 0})


def safe_sklearn_metric(name: str, labels_a: list[int], labels_b: list[int]) -> float | None:
    if len(labels_a) != len(labels_b) or not labels_a:
        return None
    try:
        if name == "ari":
            from sklearn.metrics import adjusted_rand_score

            return float(adjusted_rand_score(labels_a, labels_b))
        if name == "nmi":
            from sklearn.metrics import normalized_mutual_info_score

            return float(normalized_mutual_info_score(labels_a, labels_b))
    except Exception:
        return None
    return None


def build_metric_payload(
    texts: list[str],
    labels: list[int],
    topic_words: list[list[str]],
    embeddings: Any | None = None,
) -> dict[str, Any]:
    tokenized = [tokenize(text) for text in texts]
    metrics: dict[str, Any] = {
        "topic_coherence": umass_coherence(tokenized, topic_words),
        "topic_diversity": topic_diversity(topic_words),
        "outlier_ratio": outlier_ratio(labels),
        "cluster_count": cluster_count(labels),
    }
    if embeddings is not None and cluster_count(labels) >= 2:
        try:
            from sklearn.metrics import davies_bouldin_score, silhouette_score

            non_outlier = [i for i, label in enumerate(labels) if label >= 0]
            if len({labels[i] for i in non_outlier}) >= 2 and len(non_outlier) > 2:
                x = embeddings[non_outlier]
                y = [labels[i] for i in non_outlier]
                metrics["silhouette"] = float(silhouette_score(x, y))
                metrics["davies_bouldin"] = float(davies_bouldin_score(x, y))
            else:
                metrics["silhouette"] = None
                metrics["davies_bouldin"] = None
        except Exception:
            metrics["silhouette"] = None
            metrics["davies_bouldin"] = None
    else:
        metrics["silhouette"] = None
        metrics["davies_bouldin"] = None
    return metrics
