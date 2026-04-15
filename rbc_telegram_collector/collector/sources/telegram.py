from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from telethon import TelegramClient, utils
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.types import Message

from collector.models import CollectedMessage
from collector.sources.base import Source


def _env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _coerce_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _peer_id(peer: Optional[types.TypePeer]) -> Optional[int]:
    if peer is None:
        return None
    return utils.get_peer_id(peer, add_mark=False)


def _forward_origin_type(fwd_from: Optional[types.MessageFwdHeader]) -> Optional[str]:
    if fwd_from is None:
        return None
    if fwd_from.saved_from_peer is not None:
        return "saved_from_peer"
    if fwd_from.saved_from_id is not None:
        return "saved_from_id"
    if isinstance(fwd_from.from_id, types.PeerChannel):
        return "channel"
    if isinstance(fwd_from.from_id, types.PeerUser):
        return "user"
    if fwd_from.from_name:
        return "hidden_user"
    return "unknown"


def _forward_from_channel_name(
    msg: Message,
    fwd_from: Optional[types.MessageFwdHeader],
) -> Optional[str]:
    if fwd_from is None:
        return None

    forward = getattr(msg, "forward", None)
    if forward is not None:
        chat = getattr(forward, "chat", None)
        if getattr(chat, "username", None):
            return chat.username
        if getattr(chat, "title", None):
            return chat.title
        if getattr(forward, "from_name", None):
            return forward.from_name
        if getattr(forward, "post_author", None):
            return forward.post_author

    if fwd_from.from_name:
        return fwd_from.from_name
    if fwd_from.post_author:
        return fwd_from.post_author
    return None


class TelegramChannelSource(Source):
    def __init__(self, *, session_name: str = "telegram", workdir: str = "."):
        api_id = int(_env_required("TG_API_ID"))
        api_hash = _env_required("TG_API_HASH")

        string_session = os.getenv("TG_STRING_SESSION")
        if string_session:
            session = StringSession(string_session)
        else:
            # Will create <session_name>.session in workdir (interactive login on first run)
            session = session_name

        self.client = TelegramClient(
            session,
            api_id,
            api_hash,
            device_model="collector",
            system_version="1.0",
        )
        self.workdir = workdir

    async def __aenter__(self):
        await self.client.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.disconnect()

    async def iter_messages(
        self,
        channel: str,
        since: Optional[date],
        min_id_exclusive: Optional[int],
        limit: Optional[int],
    ) -> AsyncIterator[CollectedMessage]:
        # channel can be "rbc_news" or "@rbc_news" or "https://t.me/rbc_news"
        ch = channel.strip()
        if ch.startswith("https://t.me/"):
            ch = ch.replace("https://t.me/", "").strip("/")
        if ch.startswith("@"):
            ch = ch[1:]

        since_dt_utc: Optional[datetime] = None
        if since:
            since_dt_utc = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)

        if since_dt_utc:
            reverse_order = False
        else:
            reverse_order = True

        iter_params = {
            "reverse": reverse_order,
            "limit": limit,
        }

        if min_id_exclusive:
            iter_params["min_id"] = min_id_exclusive

        fetched = 0
        async for msg in self.client.iter_messages(ch, **iter_params):
            if not isinstance(msg, Message):
                continue
            if not msg.date:
                continue

            msg_dt = _coerce_utc(msg.date)
            if msg_dt is None:
                continue
            if since_dt_utc and msg_dt < since_dt_utc:
                break

            text = msg.message or ""
            channel_id = _peer_id(getattr(msg, "peer_id", None))
            views = getattr(msg, "views", None)
            forwards = getattr(msg, "forwards", None)
            grouped_id = getattr(msg, "grouped_id", None)
            edit_date = _coerce_utc(getattr(msg, "edit_date", None))
            post_author = getattr(msg, "post_author", None)

            replies = None
            if getattr(msg, "replies", None) is not None:
                replies = getattr(msg.replies, "replies", None)

            reply_to = getattr(msg, "reply_to", None)
            reply_to_message_id = None
            reply_to_top_message_id = None
            if isinstance(reply_to, types.MessageReplyHeader):
                reply_to_message_id = reply_to.reply_to_msg_id
                reply_to_top_message_id = reply_to.reply_to_top_id

            fwd_from = getattr(msg, "fwd_from", None)
            forward_from_channel_id = None
            if fwd_from is not None:
                if isinstance(fwd_from.from_id, types.PeerChannel):
                    forward_from_channel_id = _peer_id(fwd_from.from_id)
                elif isinstance(fwd_from.saved_from_peer, types.PeerChannel):
                    forward_from_channel_id = _peer_id(fwd_from.saved_from_peer)

            forward_from_message_id = None
            if fwd_from is not None:
                forward_from_message_id = (
                    fwd_from.channel_post
                    if fwd_from.channel_post is not None
                    else fwd_from.saved_from_msg_id
                )

            forward_date = _coerce_utc(getattr(fwd_from, "date", None))
            forward_origin_type = _forward_origin_type(fwd_from)
            forward_from_channel = _forward_from_channel_name(msg, fwd_from)
            is_forwarded = fwd_from is not None
            permalink = f"https://t.me/{ch}/{msg.id}"

            media: Optional[Dict[str, Any]] = None
            if msg.media:
                media = {"type": msg.media.__class__.__name__}

            raw = {
                "id": msg.id,
                "date": msg_dt.isoformat(),
                "channel_id": channel_id,
                "text": text,
                "views": views,
                "forwards": forwards,
                "replies": replies,
                "has_media": bool(msg.media),
                "permalink": permalink,
                "grouped_id": grouped_id,
                "edit_date": edit_date.isoformat() if edit_date else None,
                "reply_to_message_id": reply_to_message_id,
                "reply_to_top_message_id": reply_to_top_message_id,
                "post_author": post_author,
                "is_forwarded": is_forwarded,
                "forward_from_channel": forward_from_channel,
                "forward_from_channel_id": forward_from_channel_id,
                "forward_from_message_id": forward_from_message_id,
                "forward_date": forward_date.isoformat() if forward_date else None,
                "forward_origin_type": forward_origin_type,
            }

            yield CollectedMessage(
                source="telegram",
                channel=ch,
                message_id=msg.id,
                date_utc=msg_dt,
                text=text,
                channel_id=channel_id,
                views=views,
                forwards=forwards,
                replies=replies,
                permalink=permalink,
                grouped_id=grouped_id,
                edit_date=edit_date,
                reply_to_message_id=reply_to_message_id,
                reply_to_top_message_id=reply_to_top_message_id,
                post_author=post_author,
                is_forwarded=is_forwarded,
                forward_from_channel=forward_from_channel,
                forward_from_channel_id=forward_from_channel_id,
                forward_from_message_id=forward_from_message_id,
                forward_date=forward_date,
                forward_origin_type=forward_origin_type,
                media=media,
                raw=raw,
            )

            fetched += 1
            if limit is not None and fetched >= limit:
                break
