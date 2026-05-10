from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from paper_detector.config import AppConfig
from paper_detector.service import PaperDetectorService


def main() -> int:
    config_path = Path("config.yaml")
    if not config_path.exists():
        config_path = Path("config.example.yaml")
    config = AppConfig.from_yaml(config_path)

    logging.basicConfig(
        level=config.service.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    svc = PaperDetectorService(config)
    asyncio.run(svc.start())
    return 0
