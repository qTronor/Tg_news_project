from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from analytics_api.config import load_config
from analytics_api.service import AnalyticsApiService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run analytics API service")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("analytics_api/config.yaml"),
        help="Path to config YAML",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    service = AnalyticsApiService(config)
    asyncio.run(service.run())
