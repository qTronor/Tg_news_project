from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from training_orchestrator.config import load_config
from training_orchestrator.service import TrainingOrchestratorService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run training orchestrator service")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("training_orchestrator/config.yaml"),
        help="Path to config YAML",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(TrainingOrchestratorService(config).run())
