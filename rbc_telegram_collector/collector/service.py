from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from collector.runner import collect_once, load_config


class CollectorService:
    def __init__(self, config_path: str) -> None:
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        self._stop_event = asyncio.Event()
        self.log = logging.getLogger("collector.service")

    def request_stop(self) -> None:
        self._stop_event.set()

    def _install_signal_handlers(self) -> None:
        for signame in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, signame, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, lambda *_: self.request_stop())
            except (ValueError, OSError):
                continue

    async def run_once(self) -> None:
        results = await collect_once(self.config)
        total = sum(results.values())
        self.log.info("Collection cycle finished: results=%s total=%s", results, total)

    async def run_cycle(self) -> None:
        try:
            await self.run_once()
        except Exception:
            self.log.exception("Collection cycle failed")

    async def run(self) -> None:
        self._install_signal_handlers()
        await self.run_cycle()

        if not self.config.scheduler.enabled:
            self.log.info("Scheduler disabled; service exits after a single collection cycle.")
            return

        interval = self.config.scheduler.interval_seconds
        self.log.info("Scheduler enabled; collection interval=%s seconds", interval)

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                await self.run_cycle()

        self.log.info("Stop signal received; collector service is shutting down.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector.service",
        description="Run the Telegram collector as a long-lived scheduled service",
    )
    parser.add_argument("--config", default="config.yaml")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    asyncio.run(CollectorService(args.config).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
