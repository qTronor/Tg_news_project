from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Optional, Dict


@dataclass(frozen=True)
class CollectedMessage:
    source: str                 # e.g. "telegram"
    channel: str                # e.g. "rbc_news"
    message_id: int
    date_utc: datetime
    text: str

    # extra metadata (optional)
    channel_id: Optional[int] = None
    views: Optional[int] = None
    forwards: Optional[int] = None
    replies: Optional[int] = None
    permalink: Optional[str] = None
    grouped_id: Optional[int] = None
    edit_date: Optional[datetime] = None
    reply_to_message_id: Optional[int] = None
    reply_to_top_message_id: Optional[int] = None
    post_author: Optional[str] = None
    is_forwarded: bool = False
    forward_from_channel: Optional[str] = None
    forward_from_channel_id: Optional[int] = None
    forward_from_message_id: Optional[int] = None
    forward_date: Optional[datetime] = None
    forward_origin_type: Optional[str] = None
    media: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["date_utc"] = self.date_utc.isoformat()
        if self.edit_date is not None:
            d["edit_date"] = self.edit_date.isoformat()
        if self.forward_date is not None:
            d["forward_date"] = self.forward_date.isoformat()
        return d
