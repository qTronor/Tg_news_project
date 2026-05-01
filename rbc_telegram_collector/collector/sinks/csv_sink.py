from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List

from collector.models import CollectedMessage
from collector.sinks.base import Sink


class CsvSink(Sink):
    def __init__(self, path: Path):
        self.path = path

    def write(self, items: Iterable[CollectedMessage]) -> int:
        rows: List[dict] = [m.to_dict() for m in items]
        if not rows:
            return 0

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys())
        file_exists = self.path.exists()

        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(rows)
        return len(rows)
