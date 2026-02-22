from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from message_persister.config import load_config
from message_persister.logging_utils import setup_logging
from message_persister.service import MessagePersisterService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kafka raw message persister")
    parser.add_argument(
        "--config",
        default=os.environ.get("MESSAGE_PERSISTER_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    service = MessagePersisterService(config)
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.request_stop()
    return 0
