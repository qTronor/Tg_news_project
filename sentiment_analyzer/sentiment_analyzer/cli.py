from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from sentiment_analyzer.config import load_config
from sentiment_analyzer.logging_utils import setup_logging
from sentiment_analyzer.service import SentimentAnalyzerService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka sentiment analyzer service")
    parser.add_argument(
        "--config",
        default=os.environ.get("SENTIMENT_ANALYZER_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    service = SentimentAnalyzerService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.request_stop()
    return 0
