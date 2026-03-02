from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import duckdb

from analytics_duckdb.config import AppConfig


class AnalyticsDuckDB:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lake_path = config.lake_path
        self._conn = duckdb.connect(database=":memory:")
        self._configure_runtime()
        self._init_views()

    def close(self) -> None:
        self._conn.close()

    def _configure_runtime(self) -> None:
        if self._config.duckdb.threads:
            self._conn.execute(f"PRAGMA threads={int(self._config.duckdb.threads)};")
        if self._config.duckdb.memory_limit:
            limit = self._config.duckdb.memory_limit.replace("'", "")
            self._conn.execute(f"PRAGMA memory_limit='{limit}';")

    def _has_parquet(self, relative_path: str) -> bool:
        base = self._lake_path / relative_path
        return base.exists() and any(base.rglob("*.parquet"))

    def _glob(self, relative_path: str) -> str:
        return (self._lake_path / relative_path / "**" / "*.parquet").as_posix()

    def _create_source_view(self, view_name: str, relative_path: str) -> None:
        if self._has_parquet(relative_path):
            pattern = self._glob(relative_path)
            self._conn.execute(
                f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT * FROM read_parquet('{pattern}', union_by_name=true);
                """
            )
            return
        self._conn.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM (SELECT 1) WHERE 1=0;")

    def _init_views(self) -> None:
        self._create_source_view("v_clean", "clean")
        self._create_source_view("v_topic_pred", "predictions/topic")
        self._create_source_view("v_sent_pred", "predictions/sentiment")
        self._create_source_view("v_entities", "entities")
        self._create_source_view("v_clusters", "clusters")
        self._create_source_view("v_ui_final", "ui/final")
        self._create_base_docs_view()
        self._create_entities_flat_view()

    def _create_base_docs_view(self) -> None:
        if self._has_parquet("ui/final"):
            self._conn.execute(
                """
                CREATE OR REPLACE VIEW v_base_docs AS
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    TRY_CAST(date AS TIMESTAMP) AS date_ts,
                    CAST(channel AS VARCHAR) AS channel,
                    CAST(text_snippet AS VARCHAR) AS text_snippet,
                    CAST(topic_label AS VARCHAR) AS topic_label,
                    TRY_CAST(topic_score AS DOUBLE) AS topic_score,
                    CAST(sentiment_label AS VARCHAR) AS sentiment_label,
                    TRY_CAST(sentiment_score AS DOUBLE) AS sentiment_score,
                    CAST(cluster_id AS VARCHAR) AS cluster_id,
                    TRY_CAST(cluster_prob AS DOUBLE) AS cluster_prob,
                    CAST(top_entities AS VARCHAR) AS top_entities
                FROM v_ui_final;
                """
            )
            return

        self._conn.execute(
            """
            CREATE OR REPLACE VIEW v_base_docs AS
            WITH clean_norm AS (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    TRY_CAST(date AS TIMESTAMP) AS date_ts,
                    CAST(channel AS VARCHAR) AS channel,
                    CAST(COALESCE(text_clean, text_full, '') AS VARCHAR) AS text_snippet
                FROM v_clean
            ),
            topic_norm AS (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(topic_label AS VARCHAR) AS topic_label,
                    TRY_CAST(topic_score AS DOUBLE) AS topic_score
                FROM v_topic_pred
            ),
            sent_norm AS (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(sentiment_label AS VARCHAR) AS sentiment_label,
                    TRY_CAST(sentiment_score AS DOUBLE) AS sentiment_score
                FROM v_sent_pred
            ),
            cluster_norm AS (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(cluster_id AS VARCHAR) AS cluster_id,
                    TRY_CAST(cluster_prob AS DOUBLE) AS cluster_prob
                FROM v_clusters
            )
            SELECT
                c.post_id,
                c.date_ts,
                c.channel,
                c.text_snippet,
                t.topic_label,
                t.topic_score,
                s.sentiment_label,
                s.sentiment_score,
                cl.cluster_id,
                cl.cluster_prob,
                CAST(NULL AS VARCHAR) AS top_entities
            FROM clean_norm c
            LEFT JOIN topic_norm t USING (post_id)
            LEFT JOIN sent_norm s USING (post_id)
            LEFT JOIN cluster_norm cl USING (post_id);
            """
        )

    def _create_entities_flat_view(self) -> None:
        if self._has_parquet("entities"):
            self._conn.execute(
                """
                CREATE OR REPLACE VIEW v_entities_flat AS
                SELECT CAST(post_id AS VARCHAR) AS post_id, 'PER' AS entity_type, TRIM(entity) AS entity
                FROM v_entities, UNNEST(COALESCE(PER, []::VARCHAR[])) AS t(entity)
                UNION ALL
                SELECT CAST(post_id AS VARCHAR) AS post_id, 'ORG' AS entity_type, TRIM(entity) AS entity
                FROM v_entities, UNNEST(COALESCE(ORG, []::VARCHAR[])) AS t(entity)
                UNION ALL
                SELECT CAST(post_id AS VARCHAR) AS post_id, 'LOC' AS entity_type, TRIM(entity) AS entity
                FROM v_entities, UNNEST(COALESCE(LOC, []::VARCHAR[])) AS t(entity);
                """
            )
            return

        self._conn.execute(
            """
            CREATE OR REPLACE VIEW v_entities_flat AS
            SELECT * FROM (
                SELECT
                    CAST(NULL AS VARCHAR) AS post_id,
                    CAST(NULL AS VARCHAR) AS entity_type,
                    CAST(NULL AS VARCHAR) AS entity
            ) WHERE 1=0;
            """
        )

    def _query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        cur = self._conn.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            item: Dict[str, Any] = {}
            for idx, value in enumerate(row):
                item[cols[idx]] = self._normalize_value(value)
            normalized.append(item)
        return normalized

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value

    def overview_clusters(
        self,
        date_from: str,
        date_to: str,
        channel: Optional[str],
        topic: Optional[str],
    ) -> List[Dict[str, Any]]:
        sql = """
        WITH base AS (
            SELECT *
            FROM v_base_docs
            WHERE date_ts >= ?::TIMESTAMP
              AND date_ts < ?::TIMESTAMP + INTERVAL 1 DAY
              AND (? IS NULL OR channel = ?)
              AND (? IS NULL OR topic_label = ?)
        ),
        agg AS (
            SELECT
                cluster_id,
                COUNT(*) AS size,
                AVG(sentiment_score) AS avg_sentiment_score,
                STRING_AGG(DISTINCT topic_label, ', ' ORDER BY topic_label) AS top_topics,
                STRING_AGG(DISTINCT top_entities, ', ' ORDER BY top_entities) AS top_entities
            FROM base
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id
        )
        SELECT
            cluster_id,
            size,
            ROUND(avg_sentiment_score, 4) AS avg_sentiment_score,
            top_topics,
            top_entities
        FROM agg
        ORDER BY size DESC, cluster_id
        LIMIT 200;
        """
        return self._query(
            sql,
            (date_from, date_to, channel, channel, topic, topic),
        )

    def top_entities(
        self,
        date_from: str,
        date_to: str,
        cluster_id: Optional[str],
        topic: Optional[str],
        entity_type: Optional[str],
    ) -> List[Dict[str, Any]]:
        sql = """
        WITH base AS (
            SELECT post_id
            FROM v_base_docs
            WHERE date_ts >= ?::TIMESTAMP
              AND date_ts < ?::TIMESTAMP + INTERVAL 1 DAY
              AND (? IS NULL OR cluster_id = ?)
              AND (? IS NULL OR topic_label = ?)
        )
        SELECT
            ef.entity,
            ef.entity_type,
            COUNT(*) AS count
        FROM base b
        JOIN v_entities_flat ef ON ef.post_id = b.post_id
        WHERE ef.entity IS NOT NULL
          AND ef.entity <> ''
          AND (? IS NULL OR ef.entity_type = ?)
        GROUP BY ef.entity, ef.entity_type
        ORDER BY count DESC, ef.entity
        LIMIT 200;
        """
        return self._query(
            sql,
            (
                date_from,
                date_to,
                cluster_id,
                cluster_id,
                topic,
                topic,
                entity_type,
                entity_type,
            ),
        )

    def sentiment_dynamics(
        self,
        date_from: str,
        date_to: str,
        bucket: str,
        channel: Optional[str],
        topic: Optional[str],
        cluster_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        bucket_expr = "DATE_TRUNC('hour', date_ts)" if bucket == "hour" else "DATE_TRUNC('day', date_ts)"
        sql = f"""
        SELECT
            {bucket_expr} AS bucket_ts,
            SUM(CASE WHEN sentiment_label = 'positive' THEN 1 ELSE 0 END) AS positive_count,
            SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END) AS negative_count,
            SUM(CASE WHEN sentiment_label = 'neutral' THEN 1 ELSE 0 END) AS neutral_count,
            ROUND(AVG(sentiment_score), 4) AS avg_sentiment_score
        FROM v_base_docs
        WHERE date_ts >= ?::TIMESTAMP
          AND date_ts < ?::TIMESTAMP + INTERVAL 1 DAY
          AND (? IS NULL OR channel = ?)
          AND (? IS NULL OR topic_label = ?)
          AND (? IS NULL OR cluster_id = ?)
        GROUP BY 1
        ORDER BY 1;
        """
        return self._query(
            sql,
            (
                date_from,
                date_to,
                channel,
                channel,
                topic,
                topic,
                cluster_id,
                cluster_id,
            ),
        )

    def cluster_documents(
        self,
        cluster_id: str,
        date_from: str,
        date_to: str,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        sql = """
        SELECT
            post_id,
            date_ts,
            channel,
            text_snippet,
            topic_label,
            topic_score,
            sentiment_label,
            sentiment_score,
            cluster_id,
            cluster_prob
        FROM v_base_docs
        WHERE cluster_id = ?
          AND date_ts >= ?::TIMESTAMP
          AND date_ts < ?::TIMESTAMP + INTERVAL 1 DAY
        ORDER BY date_ts DESC
        LIMIT ?
        OFFSET ?;
        """
        return self._query(sql, (cluster_id, date_from, date_to, limit, offset))

    def related_clusters(
        self,
        cluster_id: str,
        date_from: str,
        date_to: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        sql = """
        WITH cluster_entities AS (
            SELECT DISTINCT b.cluster_id, ef.entity
            FROM v_base_docs b
            JOIN v_entities_flat ef ON ef.post_id = b.post_id
            WHERE b.date_ts >= ?::TIMESTAMP
              AND b.date_ts < ?::TIMESTAMP + INTERVAL 1 DAY
              AND b.cluster_id IS NOT NULL
              AND ef.entity IS NOT NULL
              AND ef.entity <> ''
        ),
        anchor AS (
            SELECT entity
            FROM cluster_entities
            WHERE cluster_id = ?
        )
        SELECT
            ce.cluster_id AS related_cluster_id,
            COUNT(*) AS share_entities_count
        FROM cluster_entities ce
        JOIN anchor a ON a.entity = ce.entity
        WHERE ce.cluster_id <> ?
        GROUP BY ce.cluster_id
        ORDER BY share_entities_count DESC, ce.cluster_id
        LIMIT ?;
        """
        return self._query(sql, (date_from, date_to, cluster_id, cluster_id, limit))
