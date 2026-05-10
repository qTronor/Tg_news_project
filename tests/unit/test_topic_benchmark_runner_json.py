from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_benchmark_runner"))

from topic_benchmark_runner.runner import _json_object  # noqa: E402
from topic_benchmark_runner.config import AppConfig  # noqa: E402
from topic_benchmark_runner.runner import TopicBenchmarkRunner  # noqa: E402


class TopicBenchmarkRunnerJsonTest(unittest.TestCase):
    def test_json_object_accepts_dict(self) -> None:
        self.assertEqual(_json_object({"max_messages": 100}), {"max_messages": 100})

    def test_json_object_parses_json_string(self) -> None:
        self.assertEqual(_json_object('{"max_messages": 2500}'), {"max_messages": 2500})

    def test_json_object_returns_empty_dict_for_invalid_value(self) -> None:
        self.assertEqual(_json_object("not-json"), {})
        self.assertEqual(_json_object(["x"]), {})


class TopicBenchmarkRunnerDatasetDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_load_experiment_rows_uses_dataset_items_when_dataset_selected(self) -> None:
        class StubRunner(TopicBenchmarkRunner):
            def __init__(self) -> None:
                super().__init__(AppConfig())
                self.calls: list[tuple[str, object, object, object, object]] = []

            async def _load_dataset_version_rows(self, conn, dataset_version_id: str, limit: int):
                self.calls.append(("dataset", conn, dataset_version_id, limit, None))
                return ["dataset-rows"]

            async def _load_dataset(self, conn, from_dt, to_dt, channels, limit):
                self.calls.append(("window", conn, from_dt, to_dt, limit))
                return ["window-rows"]

        runner = StubRunner()

        result = await runner._load_experiment_rows(
            conn=object(),
            experiment={
                "dataset_version_id": "dataset-123",
                "window_start": None,
                "window_end": None,
                "channels": [],
            },
            max_messages=250,
        )

        self.assertEqual(result, ["dataset-rows"])
        self.assertEqual(runner.calls[0][0], "dataset")
        self.assertEqual(runner.calls[0][2], "dataset-123")

    async def test_load_experiment_rows_falls_back_to_window_query(self) -> None:
        class StubRunner(TopicBenchmarkRunner):
            def __init__(self) -> None:
                super().__init__(AppConfig())
                self.calls: list[tuple[str, object, object, object, object]] = []

            async def _load_dataset_version_rows(self, conn, dataset_version_id: str, limit: int):
                self.calls.append(("dataset", conn, dataset_version_id, limit, None))
                return ["dataset-rows"]

            async def _load_dataset(self, conn, from_dt, to_dt, channels, limit):
                self.calls.append(("window", conn, from_dt, to_dt, limit))
                return ["window-rows"]

        runner = StubRunner()

        result = await runner._load_experiment_rows(
            conn=object(),
            experiment={
                "dataset_version_id": None,
                "window_start": "from",
                "window_end": "to",
                "channels": ["rbc_news"],
            },
            max_messages=250,
        )

        self.assertEqual(result, ["window-rows"])
        self.assertEqual(runner.calls[0][0], "window")


if __name__ == "__main__":
    unittest.main()
