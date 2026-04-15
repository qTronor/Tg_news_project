from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from ner_extractor.config import load_config
from ner_extractor.logging_utils import setup_logging
from ner_extractor.service import NerExtractorService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka NER extractor service")
    parser.add_argument(
        "--config",
        default=os.environ.get("NER_EXTRACTOR_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    service = NerExtractorService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.request_stop()
    return 0
