from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from source_resolver.config import load_config
from source_resolver.service import SourceResolverService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="source_resolver",
        description="Resolve exact and inferred first sources for clustered messages",
    )
    parser.add_argument("--config", default="config.yaml")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(Path(args.config))
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(SourceResolverService(config).run())
    return 0
