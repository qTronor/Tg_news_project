from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class StateStore:
    path: Path

    def load(self) -> Dict[str, int]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: Dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_last_id(self, channel: str) -> Optional[int]:
        return self.load().get(channel)

    def set_last_id(self, channel: str, last_id: int) -> None:
        state = self.load()
        state[channel] = last_id
        self.save(state)
