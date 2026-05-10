from __future__ import annotations

import logging


def configure_logging(level: str = "INFO", service_name: str = "llm_enricher") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=f"%(asctime)s [{service_name}] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
