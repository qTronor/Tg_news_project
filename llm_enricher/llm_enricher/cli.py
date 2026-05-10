from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from llm_enricher.config import load_config
from llm_enricher.logging_utils import configure_logging
from llm_enricher.service import LLMEnricherService

logger = logging.getLogger("llm_enricher")


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM Enricher service")
    parser.add_argument("--config", type=Path, default=Path("llm_enricher/config.yaml"))
    args = parser.parse_args()

    config = load_config(args.config)
    configure_logging(config.logging.level, config.service_name)

    prompts_root = Path(__file__).parent / "prompts"

    async def run() -> None:
        svc = LLMEnricherService(config, prompts_root=prompts_root)

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(svc.stop()))
            except NotImplementedError:
                pass

        await svc.start()
        try:
            await asyncio.Event().wait()
        finally:
            await svc.stop()

    asyncio.run(run())
    return 0
