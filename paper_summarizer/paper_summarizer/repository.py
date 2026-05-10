from __future__ import annotations

import json
import asyncpg


async def insert_summary(
    pool: asyncpg.Pool,
    *,
    paper_id: str,
    model_name: str,
    prompt_version: str,
    summary_json: dict,
    short_summary: str | None,
) -> None:
    await pool.execute(
        """
        INSERT INTO scientific_paper_summaries
            (paper_id, model_name, prompt_version, summary_json, short_summary)
        VALUES ($1::uuid, $2, $3, $4::jsonb, $5)
        """,
        paper_id,
        model_name,
        prompt_version,
        json.dumps(summary_json),
        short_summary,
    )
    await pool.execute(
        "UPDATE scientific_papers SET parsing_status='parsed', updated_at=NOW() WHERE id=$1::uuid AND parsing_status != 'failed'",
        paper_id,
    )
