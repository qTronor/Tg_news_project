from __future__ import annotations

import asyncpg


async def update_paper(
    pool: asyncpg.Pool,
    *,
    paper_id: str,
    title: str | None,
    authors: list[str],
    abstract: str | None,
    published_at: str | None,
    parsing_status: str,
) -> None:
    await pool.execute(
        """
        UPDATE scientific_papers SET
            title          = $2,
            authors        = $3::jsonb,
            abstract       = $4,
            published_at   = $5::timestamptz,
            parsing_status = $6,
            updated_at     = NOW()
        WHERE id = $1::uuid
        """,
        paper_id,
        title,
        __import__("json").dumps(authors),
        abstract,
        published_at,
        parsing_status,
    )


async def insert_paper_text(
    pool: asyncpg.Pool,
    *,
    paper_id: str,
    full_text: str,
    extraction_method: str,
) -> None:
    await pool.execute(
        """
        INSERT INTO scientific_paper_texts (paper_id, full_text, extraction_method)
        VALUES ($1::uuid, $2, $3)
        ON CONFLICT DO NOTHING
        """,
        paper_id,
        full_text,
        extraction_method,
    )
