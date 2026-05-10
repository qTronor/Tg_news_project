#!/usr/bin/env python3
"""Backfill entity_canonical_id on existing ner_results rows.

Idempotent: only processes rows WHERE entity_canonical_id IS NULL.
Runs the same CanonicalResolver used in the online path to guarantee consistency.

Usage:
    python scripts/backfill_entity_canonical.py [options]

Options:
    --dsn DSN             PostgreSQL DSN (default: env NER_EXTRACTOR__POSTGRES__DSN or localhost)
    --batch-size N        Rows per batch (default: 1000)
    --limit N             Stop after N rows (default: unlimited)
    --from-date YYYY-MM-DD  Only rows with extracted_at >= date
    --to-date YYYY-MM-DD    Only rows with extracted_at <= date
    --dry-run             Print plan without writing
    --resume              Resume from last processed id (stored in /tmp/backfill_resume.txt)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "ner_extractor"))

from ner_extractor.backends.base import Entity
from ner_extractor.normalization import surface_normalize
from ner_extractor.resolver import CanonicalResolver, ResolverConfig, load_rules_from_db

RESUME_FILE = Path("/tmp/backfill_resume.txt")


async def run(args: argparse.Namespace) -> None:
    dsn = args.dsn or os.environ.get(
        "NER_EXTRACTOR__POSTGRES__DSN",
        "postgresql://postgres:postgres@localhost:5432/telegram_news",
    )

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            rules = await load_rules_from_db(conn)

        resolver = CanonicalResolver(
            ResolverConfig(
                enable_canonical_resolution=True,
                fuzzy_threshold=0.88,
                auto_create_threshold=0.85,
                link_threshold=0.70,
            ),
            rules=rules,
        )

        last_id = None
        if args.resume and RESUME_FILE.exists():
            last_id = RESUME_FILE.read_text().strip() or None
            print(f"Resuming from id > {last_id}")

        total_processed = 0
        total_linked = 0

        while True:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    build_query(args, last_id),
                    *build_params(args, last_id),
                )

            if not rows:
                break

            print(f"Batch: {len(rows)} rows (last_id={last_id})")

            for row in rows:
                entity = Entity(
                    text=row["entity_text"],
                    entity_type=row["entity_type"],
                    start=row["start_pos"] or 0,
                    end=row["end_pos"] or 0,
                    confidence=float(row["confidence"] or 1.0),
                    normalized=row["normalized_text"],
                )
                language = row["model_language"] or "ru"

                if args.dry_run:
                    norm = surface_normalize(entity.normalized or entity.text, language)
                    print(f"  [dry-run] id={row['id']} text={entity.text!r} norm={norm!r}")
                else:
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            resolved = await resolver.resolve(
                                conn, entity, str(row["id"]), language
                            )
                            if resolved.canonical_id:
                                import uuid as _uuid
                                await conn.execute(
                                    "UPDATE ner_results SET entity_canonical_id = $1 WHERE id = $2",
                                    _uuid.UUID(resolved.canonical_id),
                                    row["id"],
                                )
                                total_linked += 1

                last_id = str(row["id"])
                total_processed += 1

            if args.limit and total_processed >= args.limit:
                print(f"Reached limit={args.limit}, stopping.")
                break

            # Save resume point
            if not args.dry_run:
                RESUME_FILE.write_text(last_id or "")

            print(f"Progress: processed={total_processed} linked={total_linked}")

        print(f"\nDone. total_processed={total_processed} total_linked={total_linked}")
        remaining = await _count_remaining(pool)
        print(f"Remaining NULL entity_canonical_id rows: {remaining}")

    finally:
        await pool.close()


def build_query(args: argparse.Namespace, last_id: str | None) -> str:
    parts = ["SELECT id, entity_text, entity_type, start_pos, end_pos, confidence, normalized_text, model_language"]
    parts.append("FROM ner_results WHERE entity_canonical_id IS NULL")
    params: list[str] = []
    param_idx = 1
    if last_id:
        parts.append(f"AND id > ${param_idx}::uuid")
        param_idx += 1
    if args.from_date:
        parts.append(f"AND extracted_at >= ${param_idx}::date")
        param_idx += 1
    if args.to_date:
        parts.append(f"AND extracted_at <= ${param_idx}::date")
        param_idx += 1
    parts.append(f"ORDER BY id ASC LIMIT ${param_idx}")
    return "\n".join(parts)


def build_params(args: argparse.Namespace, last_id: str | None) -> list:
    params = []
    if last_id:
        params.append(last_id)
    if args.from_date:
        params.append(args.from_date)
    if args.to_date:
        params.append(args.to_date)
    batch = args.batch_size
    if args.limit:
        remaining_limit = args.limit - (args.current_processed if hasattr(args, "current_processed") else 0)
        batch = min(batch, remaining_limit)
    params.append(batch)
    return params


async def _count_remaining(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM ner_results WHERE entity_canonical_id IS NULL") or 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill entity_canonical_id on ner_results")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
