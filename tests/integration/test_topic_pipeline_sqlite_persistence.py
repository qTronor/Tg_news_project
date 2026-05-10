from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "topic_clusterer"))

from topic_clusterer.config import AppConfig, StorageConfig  # noqa: E402
from topic_clusterer.service import ClusteringRunBatch, TopicClustererService  # noqa: E402


def test_clustering_run_persists_legacy_sqlite_results(tmp_path: Path) -> None:
    db_path = tmp_path / "topic_clusters.db"
    service = TopicClustererService(
        AppConfig(storage=StorageConfig(db_path=str(db_path), parquet_dir=str(tmp_path / "parquet")))
    )
    service._start_embeddings_db()
    now = datetime(2026, 5, 2, tzinfo=timezone.utc)
    batch = ClusteringRunBatch(
        run_id="run_test",
        run_timestamp=now,
        algo_version="similarity_fallback_v1.0.0",
        window_start=now,
        window_end=now,
        total_messages=2,
        total_clustered=2,
        total_noise=0,
        n_clusters=1,
        config_json={
            "model_version": "1.0.0",
            "config_hash": "abc123",
            "dataset_version": "test",
            "embedding_model": "baseline",
            "metrics": {"mean_probability": 0.9},
        },
        duration_seconds=0.1,
        assignments=[
            {
                "event_id": "c1:1",
                "channel": "c1",
                "message_id": 1,
                "cluster_id": 0,
                "cluster_probability": 0.91,
                "bucket_id": "b1",
            },
            {
                "event_id": "c1:2",
                "channel": "c1",
                "message_id": 2,
                "cluster_id": 0,
                "cluster_probability": 0.89,
                "bucket_id": "b1",
            },
        ],
        topic_metadata={},
    )

    try:
        service._record_clustering_run_sqlite(batch)

        assert service._db is not None
        run = service._db.execute("SELECT run_id, n_clusters FROM cluster_runs").fetchone()
        rows = service._db.execute("SELECT event_id, cluster_id FROM cluster_results ORDER BY event_id").fetchall()
        assert run == ("run_test", 1)
        assert rows == [("c1:1", 0), ("c1:2", 0)]
    finally:
        if service._db is not None:
            service._db.close()
