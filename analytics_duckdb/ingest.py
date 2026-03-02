from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from analytics_duckdb.ingest_job import ingest_colab_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Colab parquet outputs into lake layout")
    parser.add_argument(
        "--colab-outputs-path",
        default=os.environ.get("COLAB_OUTPUTS_PATH", "colab_outputs"),
        help="Path to folder with Colab .parquet files",
    )
    parser.add_argument(
        "--lake-path",
        default=os.environ.get("LAKE_PATH", "lake"),
        help="Path to target lake root directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = ingest_colab_outputs(
        colab_outputs_path=Path(args.colab_outputs_path),
        lake_path=Path(args.lake_path),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
