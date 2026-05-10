from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analytics_api"))

from analytics_api.service import _benchmark_model_name, _experiment_summary, _utc_iso  # noqa: E402


class TopicBenchmarkApiPayloadTest(unittest.TestCase):
    def test_benchmark_model_name_knows_required_models(self) -> None:
        self.assertIn("SBERT", _benchmark_model_name("sbert_umap_hdbscan"))
        self.assertIn("Latent", _benchmark_model_name("lda"))
        self.assertIn("Non-negative", _benchmark_model_name("nmf"))

    def test_utc_iso_serializes_datetime_for_api(self) -> None:
        value = datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)

        self.assertEqual(_utc_iso(value), "2026-05-02T10:00:00Z")

    def test_experiment_summary_exposes_dataset_link(self) -> None:
        dataset_id = uuid4()
        row = {
            "id": uuid4(),
            "name": "bench",
            "description": None,
            "dataset_version": "rbc-apr",
            "dataset_version_id": dataset_id,
            "window_start": datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
            "window_end": datetime(2026, 5, 2, 0, 0, tzinfo=timezone.utc),
            "channels": ["rbc_news"],
            "seed": 42,
            "status": "created",
            "created_at": datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc),
            "run_count": 4,
            "completed_run_count": 1,
        }

        payload = _experiment_summary(row)

        self.assertEqual(payload["dataset_version"], "rbc-apr")
        self.assertEqual(payload["dataset_version_id"], str(dataset_id))


if __name__ == "__main__":
    unittest.main()
