from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import duckdb


@dataclass(frozen=True)
class ArtifactSpec:
    filename: str
    relative_output: str
    required_columns: List[str]
    copy_sql: str
    has_date: bool


ARTIFACTS = [
    ArtifactSpec(
        filename="telegram_clean.parquet",
        relative_output="clean",
        required_columns=["post_id", "channel"],
        has_date=True,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    TRY_CAST(date AS TIMESTAMP) AS date,
                    CAST(channel AS VARCHAR) AS channel,
                    CAST(text_clean AS VARCHAR) AS text_clean,
                    CAST(text_full AS VARCHAR) AS text_full,
                    COALESCE(STRFTIME(TRY_CAST(date AS TIMESTAMP), '%Y-%m-%d'), 'unknown') AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt, channel), OVERWRITE_OR_IGNORE 1);
        """,
    ),
    ArtifactSpec(
        filename="topic_predictions.parquet",
        relative_output="predictions/topic",
        required_columns=["post_id", "topic_label", "topic_score"],
        has_date=False,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(topic_label AS VARCHAR) AS topic_label,
                    TRY_CAST(topic_score AS DOUBLE) AS topic_score,
                    'unknown' AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt), OVERWRITE_OR_IGNORE 1);
        """,
    ),
    ArtifactSpec(
        filename="sentiment_predictions.parquet",
        relative_output="predictions/sentiment",
        required_columns=["post_id", "sentiment_label", "sentiment_score"],
        has_date=False,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(sentiment_label AS VARCHAR) AS sentiment_label,
                    TRY_CAST(sentiment_score AS DOUBLE) AS sentiment_score,
                    'unknown' AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt), OVERWRITE_OR_IGNORE 1);
        """,
    ),
    ArtifactSpec(
        filename="doc_entities.parquet",
        relative_output="entities",
        required_columns=["post_id", "PER", "ORG", "LOC"],
        has_date=False,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    COALESCE(PER, []::VARCHAR[]) AS PER,
                    COALESCE(ORG, []::VARCHAR[]) AS ORG,
                    COALESCE(LOC, []::VARCHAR[]) AS LOC,
                    'unknown' AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt), OVERWRITE_OR_IGNORE 1);
        """,
    ),
    ArtifactSpec(
        filename="clusters.parquet",
        relative_output="clusters",
        required_columns=["post_id", "cluster_id", "cluster_prob", "topic_label", "bucket_id"],
        has_date=True,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    CAST(cluster_id AS VARCHAR) AS cluster_id,
                    TRY_CAST(cluster_prob AS DOUBLE) AS cluster_prob,
                    CAST(topic_label AS VARCHAR) AS topic_label,
                    TRY_CAST(date AS TIMESTAMP) AS date,
                    CAST(bucket_id AS VARCHAR) AS bucket_id,
                    COALESCE(CAST(window_hours AS VARCHAR), 'unknown') AS window_hours,
                    COALESCE(STRFTIME(TRY_CAST(date AS TIMESTAMP), '%Y-%m-%d'), 'unknown') AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt, window_hours), OVERWRITE_OR_IGNORE 1);
        """,
    ),
    ArtifactSpec(
        filename="final_table.parquet",
        relative_output="ui/final",
        required_columns=[
            "post_id",
            "channel",
            "text_snippet",
            "topic_label",
            "topic_score",
            "sentiment_label",
            "sentiment_score",
            "cluster_id",
            "cluster_prob",
        ],
        has_date=True,
        copy_sql="""
            COPY (
                SELECT
                    CAST(post_id AS VARCHAR) AS post_id,
                    TRY_CAST(date AS TIMESTAMP) AS date,
                    CAST(channel AS VARCHAR) AS channel,
                    CAST(text_snippet AS VARCHAR) AS text_snippet,
                    CAST(topic_label AS VARCHAR) AS topic_label,
                    TRY_CAST(topic_score AS DOUBLE) AS topic_score,
                    CAST(sentiment_label AS VARCHAR) AS sentiment_label,
                    TRY_CAST(sentiment_score AS DOUBLE) AS sentiment_score,
                    CAST(cluster_id AS VARCHAR) AS cluster_id,
                    TRY_CAST(cluster_prob AS DOUBLE) AS cluster_prob,
                    CAST(top_entities AS VARCHAR) AS top_entities,
                    COALESCE(STRFTIME(TRY_CAST(date AS TIMESTAMP), '%Y-%m-%d'), 'unknown') AS dt
                FROM read_parquet('{input_path}')
            ) TO '{output_path}'
            (FORMAT PARQUET, PARTITION_BY (dt), OVERWRITE_OR_IGNORE 1);
        """,
    ),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _quoted(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _read_columns(conn: duckdb.DuckDBPyConnection, parquet_path: Path) -> List[str]:
    query = f"DESCRIBE SELECT * FROM read_parquet('{_quoted(parquet_path)}')"
    rows = conn.execute(query).fetchall()
    return [row[0] for row in rows]


def _read_stat(conn: duckdb.DuckDBPyConnection, parquet_path: Path, has_date: bool) -> Dict[str, str]:
    if has_date:
        query = f"""
            SELECT
                CAST(COUNT(*) AS BIGINT) AS row_count,
                COALESCE(STRFTIME(MIN(TRY_CAST(date AS TIMESTAMP)), '%Y-%m-%d'), 'unknown') AS min_dt,
                COALESCE(STRFTIME(MAX(TRY_CAST(date AS TIMESTAMP)), '%Y-%m-%d'), 'unknown') AS max_dt
            FROM read_parquet('{_quoted(parquet_path)}');
        """
    else:
        query = f"""
            SELECT
                CAST(COUNT(*) AS BIGINT) AS row_count,
                'unknown' AS min_dt,
                'unknown' AS max_dt
            FROM read_parquet('{_quoted(parquet_path)}');
        """
    row = conn.execute(query).fetchone()
    return {
        "row_count": int(row[0]),
        "min_dt": str(row[1]),
        "max_dt": str(row[2]),
    }


def _load_watermark(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"datasets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def ingest_colab_outputs(colab_outputs_path: Path, lake_path: Path) -> Dict[str, object]:
    conn = duckdb.connect(database=":memory:")
    lake_path.mkdir(parents=True, exist_ok=True)
    meta_dir = lake_path / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    watermark_path = meta_dir / "watermarks.json"
    watermark = _load_watermark(watermark_path)

    datasets = dict(watermark.get("datasets", {}))

    for artifact in ARTIFACTS:
        source_file = colab_outputs_path / artifact.filename
        if not source_file.exists():
            continue

        columns = _read_columns(conn, source_file)
        missing_columns = [col for col in artifact.required_columns if col not in columns]
        if missing_columns:
            raise ValueError(
                f"{artifact.filename}: missing required columns {missing_columns}; found={columns}"
            )

        output_root = lake_path / artifact.relative_output
        output_root.mkdir(parents=True, exist_ok=True)
        copy_sql = artifact.copy_sql.format(
            input_path=_quoted(source_file),
            output_path=_quoted(output_root),
        )
        conn.execute(copy_sql)

        stat = _read_stat(conn, source_file, artifact.has_date)
        datasets[artifact.relative_output] = {
            "source_file": source_file.name,
            "ingested_at": _now_iso(),
            **stat,
        }

    payload = {
        "updated_at": _now_iso(),
        "source_path": str(colab_outputs_path),
        "lake_path": str(lake_path),
        "datasets": datasets,
    }
    watermark_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    conn.close()
    return payload
