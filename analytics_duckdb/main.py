from __future__ import annotations

import argparse
import os
from pathlib import Path

from aiohttp import web

from analytics_duckdb.api import create_app
from analytics_duckdb.config import load_config
from analytics_duckdb.duckdb_store import AnalyticsDuckDB
from analytics_duckdb.logging_utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DuckDB analytics API over Parquet lake")
    parser.add_argument(
        "--config",
        default=os.environ.get("ANALYTICS_DUCKDB_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    store = AnalyticsDuckDB(config)
    app = create_app(store)
    try:
        web.run_app(app, host=config.api.host, port=config.api.port)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
