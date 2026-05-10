from __future__ import annotations

import asyncpg


async def insert_paper(
    pool: asyncpg.Pool,
    *,
    source_message_id: str,
    source_channel: str,
    source_url: str | None,
    source_type: str,
    telegram_file_id: str | None,
    detected_at: str,
) -> str | None:
    """Insert into scientific_papers, return UUID or None if duplicate."""
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO scientific_papers
                (source_message_id, source_channel, source_url, source_type,
                 telegram_file_id, detected_at, parsing_status)
            VALUES ($1, $2, $3, $4, $5, $6::timestamptz, 'detected')
            ON CONFLICT (source_url) WHERE source_url IS NOT NULL DO NOTHING
            RETURNING id::text
            """,
            source_message_id,
            source_channel,
            source_url,
            source_type,
            telegram_file_id,
            detected_at,
        )
        return row["id"] if row else None
    except Exception:
        raise
