from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from topic_benchmark_runner.config import load_config
from topic_benchmark_runner.runner import TopicBenchmarkRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run topic modeling benchmarks")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run a new benchmark experiment")
    run.add_argument("--from", dest="from_dt", required=True)
    run.add_argument("--to", dest="to_dt", required=True)
    run.add_argument("--channels", default="", help="Comma-separated channel names")
    run.add_argument("--models", default="", help="Comma-separated model keys")
    run.add_argument("--dataset-version", default="manual")
    run.add_argument("--name", default="topic-benchmark")
    run.add_argument("--max-messages", type=int)
    run.add_argument("--seed", type=int)
    run.add_argument("--n-topics", type=int)
    run_existing = sub.add_parser("run-existing", help="Run queued model configs for an existing experiment")
    run_existing.add_argument("--experiment-id", required=True)
    worker = sub.add_parser("worker", help="Poll and execute queued experiments")
    worker.add_argument("--once", action="store_true", help="Process at most one queued experiment and exit")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        runner = TopicBenchmarkRunner(config)
        models = [item.strip() for item in args.models.split(",") if item.strip()]
        channels = [item.strip() for item in args.channels.split(",") if item.strip()]
        result = asyncio.run(
            runner.run_new_experiment(
                name=args.name,
                from_dt=args.from_dt,
                to_dt=args.to_dt,
                channels=channels,
                models=models or None,
                dataset_version=args.dataset_version,
                max_messages=args.max_messages,
                seed=args.seed,
                n_topics=args.n_topics,
            )
        )
        print(result)
        return 0
    if args.command == "run-existing":
        runner = TopicBenchmarkRunner(config)
        result = asyncio.run(runner.run_existing_experiment(args.experiment_id))
        print(result)
        return 0
    if args.command == "worker":
        runner = TopicBenchmarkRunner(config)
        result = asyncio.run(runner.run_worker(once=args.once))
        print(result)
        return 0
    return 1
