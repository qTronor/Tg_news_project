from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import aiohttp
import duckdb
import pytest
from aiohttp import web

SERVICE_DIR = Path(__file__).resolve().parents[2] / "analytics_duckdb"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from analytics_duckdb.api import create_app
from analytics_duckdb.config import AppConfig
from analytics_duckdb.duckdb_store import AnalyticsDuckDB
from analytics_duckdb.ingest_job import ingest_colab_outputs


def _copy_parquet(conn: duckdb.DuckDBPyConnection, sql_query: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(
        f"COPY ({sql_query}) TO '{target_path.as_posix()}' (FORMAT PARQUET);"
    )


def _build_colab_outputs(base_dir: Path) -> Path:
    outputs = base_dir / "colab_outputs"
    conn = duckdb.connect(database=":memory:")

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', TIMESTAMP '2026-01-02 10:00:00', 'rbc_news', 'txt1 clean', 'txt1 full'),
                ('p2', TIMESTAMP '2026-01-02 11:00:00', 'rbc_news', 'txt2 clean', 'txt2 full'),
                ('p3', TIMESTAMP '2026-01-03 12:00:00', 'cbpub', 'txt3 clean', 'txt3 full')
        ) AS t(post_id, date, channel, text_clean, text_full)
        """,
        outputs / "telegram_clean.parquet",
    )

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', 'economy', 0.91),
                ('p2', 'economy', 0.88),
                ('p3', 'politics', 0.73)
        ) AS t(post_id, topic_label, topic_score)
        """,
        outputs / "topic_predictions.parquet",
    )

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', 'positive', 0.71),
                ('p2', 'negative', 0.22),
                ('p3', 'neutral', 0.51)
        ) AS t(post_id, sentiment_label, sentiment_score)
        """,
        outputs / "sentiment_predictions.parquet",
    )

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', ['Иванов'], ['ЦБ РФ'], ['Москва']),
                ('p2', ['Петров'], ['Минфин'], ['Москва']),
                ('p3', ['Сидоров'], ['Госдума', 'Минфин'], ['Санкт-Петербург'])
        ) AS t(post_id, PER, ORG, LOC)
        """,
        outputs / "doc_entities.parquet",
    )

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', 'c1', 0.95, 'economy', TIMESTAMP '2026-01-02 10:00:00', 'b1', 24),
                ('p2', 'c1', 0.89, 'economy', TIMESTAMP '2026-01-02 11:00:00', 'b1', 24),
                ('p3', 'c2', 0.93, 'politics', TIMESTAMP '2026-01-03 12:00:00', 'b2', 24)
        ) AS t(post_id, cluster_id, cluster_prob, topic_label, date, bucket_id, window_hours)
        """,
        outputs / "clusters.parquet",
    )

    _copy_parquet(
        conn,
        """
        SELECT * FROM (
            VALUES
                ('p1', TIMESTAMP '2026-01-02 10:00:00', 'rbc_news', 'snippet1', 'economy', 0.91, 'positive', 0.71, 'c1', 0.95, 'ЦБ РФ, Москва'),
                ('p2', TIMESTAMP '2026-01-02 11:00:00', 'rbc_news', 'snippet2', 'economy', 0.88, 'negative', 0.22, 'c1', 0.89, 'Минфин, Москва'),
                ('p3', TIMESTAMP '2026-01-03 12:00:00', 'cbpub', 'snippet3', 'politics', 0.73, 'neutral', 0.51, 'c2', 0.93, 'Госдума, Санкт-Петербург')
        ) AS t(
            post_id, date, channel, text_snippet, topic_label, topic_score,
            sentiment_label, sentiment_score, cluster_id, cluster_prob, top_entities
        )
        """,
        outputs / "final_table.parquet",
    )
    conn.close()
    return outputs


@pytest.mark.asyncio
async def test_duckdb_analytics_smoke(tmp_path: Path) -> None:
    colab_outputs = _build_colab_outputs(tmp_path)
    lake_path = tmp_path / "lake"
    ingest_colab_outputs(colab_outputs_path=colab_outputs, lake_path=lake_path)

    config = AppConfig(lake_path=lake_path)
    store = AnalyticsDuckDB(config)
    app = create_app(store)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # type: ignore[attr-defined]
    assert sockets and sockets[0].getsockname()
    port = sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as session:
        resp = await session.get(f"{base}/healthz")
        assert resp.status == 200

        overview = await session.get(
            f"{base}/analytics/overview/clusters",
            params={"from": "2026-01-01", "to": "2026-01-31"},
        )
        overview_json = await overview.json()
        assert overview.status == 200
        assert overview_json["count"] > 0

        entities = await session.get(
            f"{base}/analytics/entities/top",
            params={"from": "2026-01-01", "to": "2026-01-31", "entity_type": "ORG"},
        )
        entities_json = await entities.json()
        assert entities.status == 200
        assert entities_json["count"] > 0

        dynamics = await session.get(
            f"{base}/analytics/sentiment/dynamics",
            params={"from": "2026-01-01", "to": "2026-01-31", "bucket": "day"},
        )
        dynamics_json = await dynamics.json()
        assert dynamics.status == 200
        assert dynamics_json["count"] > 0

        documents = await session.get(
            f"{base}/analytics/clusters/c1/documents",
            params={"from": "2026-01-01", "to": "2026-01-31", "limit": 10, "offset": 0},
        )
        documents_json = await documents.json()
        assert documents.status == 200
        assert documents_json["count"] > 0

        related = await session.get(
            f"{base}/analytics/clusters/c1/related",
            params={"from": "2026-01-01", "to": "2026-01-31", "limit": 10},
        )
        related_json = await related.json()
        assert related.status == 200
        assert related_json["count"] > 0

    await runner.cleanup()
    store.close()
    await asyncio.sleep(0)
