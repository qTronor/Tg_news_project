from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from paper_parser.config import AppConfig
from paper_parser.service import PaperParserService


def main() -> int:
    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path("config.example.yaml")
    config = AppConfig.from_yaml(config_path)
    logging.basicConfig(level=config.service.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(PaperParserService(config).start())
    return 0
