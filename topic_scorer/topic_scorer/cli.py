from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from topic_scorer.config import load_config
from topic_scorer.logging_utils import setup_logging
from topic_scorer.service import TopicScorerService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Topic importance scorer")
    parser.add_argument(
        "--config",
        default=os.environ.get("TOPIC_SCORER_CONFIG", "config.yaml"),
        help="Path to config YAML",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    # batch: score all clusters in the latest (or given) run, then exit
    p_batch = sub.add_parser("batch", help="Score all clusters in a run and exit")
    p_batch.add_argument("--run-id", default=None, help="Cluster run ID (default: latest)")

    # oneshot: score a single cluster on demand
    p_one = sub.add_parser("oneshot", help="Score a single cluster")
    p_one.add_argument("--run-id", required=True)
    p_one.add_argument("--cluster-id", required=True, help="public_cluster_id")

    # scheduled: periodic re-scoring
    sub.add_parser("scheduled", help="Run periodic scoring (stays alive)")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(Path(args.config))
    setup_logging(config.logging.level)
    svc = TopicScorerService(config)

    try:
        if args.mode == "batch":
            asyncio.run(svc.run_batch(run_id=getattr(args, "run_id", None)))
        elif args.mode == "oneshot":
            asyncio.run(svc.run_oneshot(args.run_id, args.cluster_id))
        elif args.mode == "scheduled":
            asyncio.run(svc.run_scheduled())
    except KeyboardInterrupt:
        svc.request_stop()
    return 0
