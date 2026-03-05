from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from topic_clusterer.config import load_config
from topic_clusterer.logging_utils import setup_logging
from topic_clusterer.service import TopicClustererService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka topic clusterer service")
    parser.add_argument(
        "--config",
        default=os.environ.get("TOPIC_CLUSTERER_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    service = TopicClustererService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.request_stop()
    return 0
