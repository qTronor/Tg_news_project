from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from preprocessor.config import load_config
from preprocessor.logging_utils import setup_logging
from preprocessor.service import PreprocessorService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka message preprocessor")
    parser.add_argument(
        "--config",
        default=os.environ.get("PREPROCESSOR_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    service = PreprocessorService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.request_stop()
    return 0
