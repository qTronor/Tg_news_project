from __future__ import annotations

import sys
import unittest
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GRAPH_ANALYTICS_PATH = ROOT / "analytics_api" / "analytics_api" / "graph_analytics.py"
SPEC = importlib.util.spec_from_file_location("graph_analytics", GRAPH_ANALYTICS_PATH)
assert SPEC is not None and SPEC.loader is not None
graph_analytics = importlib.util.module_from_spec(SPEC)
sys.modules["graph_analytics"] = graph_analytics
SPEC.loader.exec_module(graph_analytics)

analyze_topic_graph = graph_analytics.analyze_topic_graph
build_topic_graph = graph_analytics.build_topic_graph


class GraphAnalyticsTest(unittest.TestCase):
    def test_topic_graph_centrality_and_bridges_are_explainable(self) -> None:
        rows = [
            {
                "event_id": "a:1",
                "channel": "a",
                "entity_key": "bank",
                "entity_text": "Bank",
                "entity_type": "ORG",
                "mention_count": 1,
            },
            {
                "event_id": "a:1",
                "channel": "a",
                "entity_key": "rate",
                "entity_text": "Rate",
                "entity_type": "MISC",
                "mention_count": 1,
            },
            {
                "event_id": "b:2",
                "channel": "b",
                "entity_key": "bank",
                "entity_text": "Bank",
                "entity_type": "ORG",
                "mention_count": 1,
            },
            {
                "event_id": "b:2",
                "channel": "b",
                "entity_key": "market",
                "entity_text": "Market",
                "entity_type": "MISC",
                "mention_count": 1,
            },
        ]

        graph = build_topic_graph(rows)
        result = analyze_topic_graph(graph["nodes"], graph["edges"])

        self.assertEqual(result["summary"]["node_count"], 5)
        self.assertGreater(result["summary"]["density"], 0)
        self.assertGreaterEqual(result["summary"]["community_count"], 1)
        top_entity_ids = [node["id"] for node in result["top_entities"]]
        self.assertEqual(top_entity_ids[0], "ent-ORG:bank")
        bridge_ids = [node["id"] for node in result["bridge_nodes"]]
        self.assertIn("ent-ORG:bank", bridge_ids)

    def test_empty_and_tiny_graphs_are_safe(self) -> None:
        empty = analyze_topic_graph([], [])
        self.assertTrue(empty["summary"]["is_small_graph"])
        self.assertEqual(empty["top_entities"], [])

        graph = build_topic_graph(
            [
                {
                    "event_id": "a:1",
                    "channel": "a",
                    "entity_key": "solo",
                    "entity_text": "Solo",
                    "entity_type": "PERSON",
                    "mention_count": 1,
                }
            ]
        )
        result = analyze_topic_graph(graph["nodes"], graph["edges"])
        self.assertTrue(result["summary"]["is_small_graph"])
        self.assertEqual(result["summary"]["component_count"], 1)
        self.assertEqual(len(result["top_channels"]), 1)


if __name__ == "__main__":
    unittest.main()
