from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Optional, Dict, List


@dataclass(frozen=True)
class CollectedMessage:
    source: str                 # e.g. "telegram"
    channel: str                # e.g. "rbc_news"
    message_id: int
    date_utc: datetime
    text: str

    # extra metadata (optional)
    views: Optional[int] = None
    forwards: Optional[int] = None
    replies: Optional[int] = None
    permalink: Optional[str] = None
    media: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date_utc"] = self.date_utc.isoformat()
        return d
