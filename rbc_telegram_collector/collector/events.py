from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from collector.models import CollectedMessage


def _normalize_media_type(media: Optional[Dict[str, Any]]) -> Optional[str]:
    if media is None:
        return None

    raw_type = media.get("type")
    if raw_type is None:
        return None

    media_type = str(raw_type).lower()
    if "photo" in media_type:
        return "photo"
    if "video" in media_type:
        return "video"
    if "document" in media_type:
        return "document"
    if "audio" in media_type:
        return "audio"
    if "voice" in media_type:
        return "voice"
    if "sticker" in media_type:
        return "sticker"
    if "animation" in media_type or "gif" in media_type:
        return "animation"
    return None


def build_raw_message_event(item: CollectedMessage) -> Tuple[str, Dict[str, Any]]:
    event_id = f"{item.channel}:{item.message_id}"
    media_type = _normalize_media_type(item.media)
    media_payload = {"type": media_type} if media_type else None

    event = {
        "event_id": event_id,
        "event_type": "raw_message",
        "event_timestamp": item.date_utc.isoformat(),
        "event_version": "v1.0.0",
        "source_system": "telegram-collector",
        "trace_id": str(uuid4()),
        "payload": {
            "message_id": item.message_id,
            "channel": item.channel,
            "channel_id": item.channel_id,
            "text": item.text,
            "date": item.date_utc.isoformat(),
            "views": item.views or 0,
            "forwards": item.forwards or 0,
            "reactions": None,
            "media": media_payload,
            "permalink": item.permalink,
            "grouped_id": item.grouped_id,
            "edit_date": item.edit_date.isoformat() if item.edit_date else None,
            "reply_to_message_id": item.reply_to_message_id,
            "reply_to_top_message_id": item.reply_to_top_message_id,
            "author": item.post_author,
            "post_author": item.post_author,
            "is_forwarded": item.is_forwarded,
            "forward_from_channel": item.forward_from_channel,
            "forward_from_channel_id": item.forward_from_channel_id,
            "forward_from_message_id": item.forward_from_message_id,
            "forward_date": item.forward_date.isoformat() if item.forward_date else None,
            "forward_origin_type": item.forward_origin_type,
        },
    }
    return event_id, event
