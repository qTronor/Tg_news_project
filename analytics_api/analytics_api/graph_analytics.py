from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Iterable


ALGO_VERSION = "local-topic-graph-v1"


@dataclass(frozen=True)
class TopicGraphNode:
    id: str
    label: str
    type: str
    weight: float = 1.0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TopicGraphEdge:
    source: str
    target: str
    weight: float = 1.0
    type: str = "related"


def build_topic_graph(entity_mentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, TopicGraphNode] = {}
    edges: dict[tuple[str, str], TopicGraphEdge] = {}
    messages: dict[str, dict[str, Any]] = defaultdict(lambda: {"channel": None, "entities": {}})

    for row in entity_mentions:
        event_id = str(row["event_id"])
        channel = str(row["channel"])
        entity_key = str(row["entity_key"])
        entity_type = str(row.get("entity_type") or "MISC").upper()
        entity_text = str(row.get("entity_text") or entity_key)
        mention_count = float(row.get("mention_count") or 1)

        channel_id = f"ch-{channel}"
        entity_id = f"ent-{entity_type}:{entity_key}"
        channel_weight = nodes[channel_id].weight if channel_id in nodes else 0.0
        entity_weight = nodes[entity_id].weight if entity_id in nodes else 0.0
        nodes[channel_id] = TopicGraphNode(
            id=channel_id,
            label=channel,
            type="channel",
            weight=channel_weight + mention_count,
        )
        nodes[entity_id] = TopicGraphNode(
            id=entity_id,
            label=entity_text,
            type=f"entity_{_ui_entity_type(entity_type).lower()}",
            weight=entity_weight + mention_count,
            metadata={"entity_type": _ui_entity_type(entity_type), "entity_key": entity_key},
        )
        messages[event_id]["channel"] = channel_id
        messages[event_id]["entities"][entity_id] = (
            messages[event_id]["entities"].get(entity_id, 0.0) + mention_count
        )

    for message in messages.values():
        channel_id = message["channel"]
        entity_weights: dict[str, float] = message["entities"]
        for entity_id, weight in entity_weights.items():
            _add_edge(edges, channel_id, entity_id, weight, "mentions")
        for left, right in combinations(sorted(entity_weights), 2):
            _add_edge(
                edges,
                left,
                right,
                min(entity_weights[left], entity_weights[right]),
                "co_occurs",
            )

    return {
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "type": node.type,
                "weight": round(node.weight, 4),
                "metadata": node.metadata or {},
            }
            for node in nodes.values()
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "weight": round(edge.weight, 4),
                "type": edge.type,
            }
            for edge in edges.values()
        ],
    }


def analyze_topic_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    adjacency = _adjacency(nodes, edges)
    node_ids = [node["id"] for node in nodes]
    node_by_id = {node["id"]: node for node in nodes}
    node_count = len(node_ids)
    edge_count = len(edges)
    components = _components(node_ids, adjacency)

    if node_count == 0:
        return _empty_result()

    degree = _degree_centrality(node_ids, adjacency)
    betweenness = _betweenness_centrality(node_ids, adjacency)
    pagerank = _pagerank(node_ids, adjacency)
    communities = _label_propagation(node_ids, adjacency)
    articulation = _articulation_points(node_ids, adjacency)
    community_count = len(set(communities.values())) if communities else 0

    top_nodes = []
    for node_id in node_ids:
        adjacent_communities = {
            communities[neighbor] for neighbor in adjacency[node_id] if neighbor in communities
        }
        bridge_score = betweenness[node_id]
        if len(adjacent_communities) >= 2:
            bridge_score += 0.2
        if node_id in articulation:
            bridge_score += 0.3
        top_nodes.append(
            {
                "id": node_id,
                "label": node_by_id[node_id].get("label", node_id),
                "type": node_by_id[node_id].get("type", "unknown"),
                "degree_centrality": round(degree[node_id], 6),
                "betweenness_centrality": round(betweenness[node_id], 6),
                "pagerank": round(pagerank[node_id], 6),
                "community_id": communities.get(node_id, 0),
                "is_bridge": bridge_score >= 0.25,
                "bridge_score": round(min(1.0, bridge_score), 6),
                "weight": node_by_id[node_id].get("weight", 1),
            }
        )

    community_payload = _community_summary(top_nodes, edges)
    density = 0.0 if node_count < 2 else (2 * edge_count) / (node_count * (node_count - 1))
    avg_degree = 0.0 if node_count == 0 else (2 * edge_count) / node_count

    return {
        "algorithm_version": ALGO_VERSION,
        "summary": {
            "node_count": node_count,
            "edge_count": edge_count,
            "density": round(density, 6),
            "average_degree": round(avg_degree, 6),
            "component_count": len(components),
            "largest_component_size": max((len(component) for component in components), default=0),
            "community_count": community_count,
            "is_small_graph": node_count < 3 or edge_count < 2,
        },
        "top_entities": _top_by_type(top_nodes, "entity_", "pagerank"),
        "top_channels": _top_by_type(top_nodes, "channel", "pagerank"),
        "bridge_nodes": sorted(
            [node for node in top_nodes if node["is_bridge"]],
            key=lambda item: (-item["bridge_score"], -item["betweenness_centrality"], item["label"]),
        )[:10],
        "communities": community_payload,
        "nodes": sorted(
            top_nodes,
            key=lambda item: (-item["pagerank"], -item["degree_centrality"], item["label"]),
        ),
    }


def _add_edge(
    edges: dict[tuple[str, str], TopicGraphEdge],
    source: str,
    target: str,
    weight: float,
    edge_type: str,
) -> None:
    if not source or not target or source == target:
        return
    key = tuple(sorted((source, target)))
    previous = edges.get(key)
    if previous is None:
        edges[key] = TopicGraphEdge(source=key[0], target=key[1], weight=weight, type=edge_type)
    else:
        merged_type = previous.type if previous.type == edge_type else "mixed"
        edges[key] = TopicGraphEdge(
            source=key[0],
            target=key[1],
            weight=previous.weight + weight,
            type=merged_type,
        )


def _adjacency(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    adjacency: dict[str, dict[str, float]] = {node["id"]: {} for node in nodes}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if source not in adjacency or target not in adjacency or source == target:
            continue
        weight = max(float(edge.get("weight") or 1), 0.0)
        adjacency[source][target] = adjacency[source].get(target, 0.0) + weight
        adjacency[target][source] = adjacency[target].get(source, 0.0) + weight
    return adjacency


def _degree_centrality(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
) -> dict[str, float]:
    denominator = max(len(node_ids) - 1, 1)
    return {node_id: len(adjacency[node_id]) / denominator for node_id in node_ids}


def _betweenness_centrality(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
) -> dict[str, float]:
    centrality = dict.fromkeys(node_ids, 0.0)
    for source in node_ids:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        sigma = dict.fromkeys(node_ids, 0.0)
        distance = dict.fromkeys(node_ids, -1)
        sigma[source] = 1.0
        distance[source] = 0
        queue = deque([source])
        while queue:
            vertex = queue.popleft()
            stack.append(vertex)
            for neighbor in adjacency[vertex]:
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[vertex] + 1
                if distance[neighbor] == distance[vertex] + 1:
                    sigma[neighbor] += sigma[vertex]
                    predecessors[neighbor].append(vertex)
        dependency = dict.fromkeys(node_ids, 0.0)
        while stack:
            vertex = stack.pop()
            for predecessor in predecessors[vertex]:
                if sigma[vertex]:
                    dependency[predecessor] += (
                        sigma[predecessor] / sigma[vertex]
                    ) * (1 + dependency[vertex])
            if vertex != source:
                centrality[vertex] += dependency[vertex]

    if len(node_ids) > 2:
        scale = 1 / ((len(node_ids) - 1) * (len(node_ids) - 2))
        centrality = {node_id: value * scale for node_id, value in centrality.items()}
    return centrality


def _pagerank(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
    damping: float = 0.85,
    iterations: int = 40,
) -> dict[str, float]:
    if not node_ids:
        return {}
    rank = dict.fromkeys(node_ids, 1.0 / len(node_ids))
    base = (1.0 - damping) / len(node_ids)
    for _ in range(iterations):
        next_rank = dict.fromkeys(node_ids, base)
        for node_id in node_ids:
            total_weight = sum(adjacency[node_id].values())
            if total_weight <= 0:
                share = damping * rank[node_id] / len(node_ids)
                for target in node_ids:
                    next_rank[target] += share
                continue
            for neighbor, weight in adjacency[node_id].items():
                next_rank[neighbor] += damping * rank[node_id] * (weight / total_weight)
        rank = next_rank
    return rank


def _label_propagation(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
    iterations: int = 20,
) -> dict[str, int]:
    labels = {node_id: index for index, node_id in enumerate(sorted(node_ids))}
    for _ in range(iterations):
        changed = False
        for node_id in sorted(node_ids):
            if not adjacency[node_id]:
                continue
            scores: Counter[int] = Counter()
            for neighbor, weight in adjacency[node_id].items():
                scores[labels[neighbor]] += weight
            best_label = min(
                scores,
                key=lambda label: (-scores[label], label),
            )
            if labels[node_id] != best_label:
                labels[node_id] = best_label
                changed = True
        if not changed:
            break
    remap = {label: index for index, label in enumerate(sorted(set(labels.values())))}
    return {node_id: remap[label] for node_id, label in labels.items()}


def _components(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
) -> list[set[str]]:
    seen: set[str] = set()
    components: list[set[str]] = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        component = set()
        queue = deque([node_id])
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def _articulation_points(
    node_ids: list[str],
    adjacency: dict[str, dict[str, float]],
) -> set[str]:
    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {node_id: None for node_id in node_ids}
    points: set[str] = set()
    time = 0

    def visit(node_id: str) -> None:
        nonlocal time
        visited.add(node_id)
        discovery[node_id] = time
        low[node_id] = time
        time += 1
        children = 0
        for neighbor in adjacency[node_id]:
            if neighbor not in visited:
                parent[neighbor] = node_id
                children += 1
                visit(neighbor)
                low[node_id] = min(low[node_id], low[neighbor])
                if parent[node_id] is None and children > 1:
                    points.add(node_id)
                if parent[node_id] is not None and low[neighbor] >= discovery[node_id]:
                    points.add(node_id)
            elif neighbor != parent[node_id]:
                low[node_id] = min(low[node_id], discovery[neighbor])

    for node_id in node_ids:
        if node_id not in visited:
            visit(node_id)
    return points


def _community_summary(
    top_nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    nodes_by_community: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in top_nodes:
        nodes_by_community[node["community_id"]].append(node)
    node_community = {node["id"]: node["community_id"] for node in top_nodes}
    internal_edges: Counter[int] = Counter()
    for edge in edges:
        source_community = node_community.get(edge["source"])
        target_community = node_community.get(edge["target"])
        if source_community is not None and source_community == target_community:
            internal_edges[source_community] += 1

    payload = []
    for community_id, nodes in sorted(nodes_by_community.items()):
        payload.append(
            {
                "community_id": community_id,
                "node_count": len(nodes),
                "edge_count": internal_edges[community_id],
                "top_nodes": sorted(
                    nodes,
                    key=lambda item: (-item["pagerank"], -item["degree_centrality"], item["label"]),
                )[:5],
                "entity_count": sum(1 for node in nodes if node["type"].startswith("entity_")),
                "channel_count": sum(1 for node in nodes if node["type"] == "channel"),
            }
        )
    return payload


def _top_by_type(nodes: list[dict[str, Any]], node_type: str, score_key: str) -> list[dict[str, Any]]:
    if node_type == "channel":
        filtered = [node for node in nodes if node["type"] == "channel"]
    else:
        filtered = [node for node in nodes if node["type"].startswith(node_type)]
    return sorted(
        filtered,
        key=lambda item: (-item[score_key], -item["degree_centrality"], item["label"]),
    )[:10]


def _empty_result() -> dict[str, Any]:
    return {
        "algorithm_version": ALGO_VERSION,
        "summary": {
            "node_count": 0,
            "edge_count": 0,
            "density": 0.0,
            "average_degree": 0.0,
            "component_count": 0,
            "largest_component_size": 0,
            "community_count": 0,
            "is_small_graph": True,
        },
        "top_entities": [],
        "top_channels": [],
        "bridge_nodes": [],
        "communities": [],
        "nodes": [],
    }


def _ui_entity_type(value: str) -> str:
    normalized = value.upper()
    if normalized in {"PERSON", "PER"}:
        return "PER"
    if normalized == "ORG":
        return "ORG"
    if normalized in {"LOC", "GPE"}:
        return "LOC"
    return "MISC"
