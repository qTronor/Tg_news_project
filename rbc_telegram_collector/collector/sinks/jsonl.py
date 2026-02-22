from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from collector.models import CollectedMessage
from collector.sinks.base import Sink


class JsonlSink(Sink):
    def __init__(self, path: Path):
        self.path = path

    def write(self, items: Iterable[CollectedMessage]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        try:
            with self.path.open("w", encoding="utf-8") as f:
                for item in items:
                    line = json.dumps(item.to_dict(), ensure_ascii=False) + "\n"
                    f.write(line)
                    f.flush()  # Принудительно записываем на диск
                    n += 1
        except Exception as e:
            import logging
            logging.getLogger("collector").error(f"Error writing to {self.path}: {e}", exc_info=True)
            raise
        return n
