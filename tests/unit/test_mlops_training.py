from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.mlops import (  # noqa: E402
    MockTrainer,
    build_training_plan,
    compare_to_baseline,
    validate_dataset_records,
)


def _topic_rows(count_a: int = 10, count_b: int = 10):
    rows = []
    for idx in range(count_a):
        rows.append({
            "item_id": f"a{idx}",
            "event_id": f"demo:a{idx}",
            "text": f"topic a text {idx}",
            "split": "train" if idx < 7 else ("validation" if idx < 9 else "test"),
            "broad_topic": "economy",
            "quality": "useful",
        })
    for idx in range(count_b):
        rows.append({
            "item_id": f"b{idx}",
            "event_id": f"demo:b{idx}",
            "text": f"topic b text {idx}",
            "split": "train" if idx < 7 else ("validation" if idx < 9 else "test"),
            "broad_topic": "politics",
            "quality": "useful",
        })
    return rows


class MlopsTrainingTest(unittest.TestCase):
    def test_invalid_dataset_without_labels(self) -> None:
        rows = [{"item_id": "1", "event_id": "demo:1", "text": "hello", "split": "train"}]

        report = validate_dataset_records({"id": "ds", "name": "ds"}, rows, "topic_classification")

        self.assertEqual(report["status"], "invalid")
        self.assertTrue(any("no labels" in err for err in report["errors"]))

    def test_invalid_dataset_with_one_class(self) -> None:
        rows = _topic_rows(count_a=12, count_b=0)

        report = validate_dataset_records({"id": "ds", "name": "ds"}, rows, "topic_classification")

        self.assertEqual(report["status"], "invalid")
        self.assertTrue(any("two classes" in err for err in report["errors"]))

    def test_warning_on_imbalance(self) -> None:
        rows = _topic_rows(count_a=60, count_b=10)

        report = validate_dataset_records({"id": "ds", "name": "ds"}, rows, "topic_classification")

        self.assertEqual(report["status"], "warning")
        self.assertTrue(any("imbalance" in msg.lower() for msg in report["warnings"]))

    def test_valid_topic_dataset(self) -> None:
        rows = _topic_rows()

        report = validate_dataset_records({"id": "ds", "name": "ds"}, rows, "topic_classification")

        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["label_distribution"], {"economy": 10, "politics": 10})

    def test_preview_does_not_create_training_job_contract(self) -> None:
        report = validate_dataset_records({"id": "ds", "name": "dataset"}, _topic_rows(), "topic_classification")

        plan = build_training_plan({"id": "ds", "name": "dataset"}, report, "topic_classification")

        self.assertFalse(plan["will_auto_deploy"])
        self.assertIn("candidate", plan["production_notice"])

    def test_mock_trainer_returns_candidate_metrics(self) -> None:
        result = MockTrainer().train(
            job_id="job1",
            task_type="sentiment_classification",
            base_model="base",
            label_distribution={"positive": 10, "negative": 10, "neutral": 10},
            training_config={"mode": "mock"},
        )

        self.assertIn("macro_f1", result.metrics)
        self.assertIn("models/candidates/sentiment_classification/job1", result.artifact_path)

    def test_comparison_to_baseline_blocks_worse_candidate(self) -> None:
        comparison = compare_to_baseline({"macro_f1": 0.72}, {"macro_f1": 0.80}, "macro_f1")

        self.assertLess(comparison["delta"], 0)
        self.assertTrue(comparison["deployment_warning"])


if __name__ == "__main__":
    unittest.main()
