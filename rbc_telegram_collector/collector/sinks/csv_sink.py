from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

import pandas as pd

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

        df = pd.DataFrame(rows)
        if self.path.exists():
            # append
            df.to_csv(self.path, mode="a", header=False, index=False, encoding="utf-8")
        else:
            df.to_csv(self.path, index=False, encoding="utf-8")
        return len(rows)
