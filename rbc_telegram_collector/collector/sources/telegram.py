from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import AsyncIterator, Optional, Dict, Any

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message

from collector.models import CollectedMessage
from collector.sources.base import Source


def _env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


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

        self.client = TelegramClient(session, api_id, api_hash, device_model="collector", system_version="1.0")
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

        # Логика сбора:
        # - Если указан since: собираем от новых к старым (reverse=False), начиная с самых новых,
        #   и останавливаемся когда достигнем даты since
        # - Если since не указан: собираем от старых к новым (reverse=True)
        if since_dt_utc:
            # Собираем от новых к старым, начиная с самых новых сообщений
            # offset_date не используем, т.к. он работает не так как нужно
            reverse_order = False
        else:
            # Собираем от старых к новым
            reverse_order = True
        
        # Параметры для iter_messages
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
            msg_dt = msg.date
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=timezone.utc)

            # Если указан since, пропускаем сообщения старше этой даты
            if since_dt_utc and msg_dt < since_dt_utc:
                # Достигли даты since, прекращаем сбор
                break

            text = msg.message or ""
            views = getattr(msg, "views", None)
            forwards = getattr(msg, "forwards", None)

            replies = None
            if getattr(msg, "replies", None) is not None:
                replies = getattr(msg.replies, "replies", None)

            permalink = f"https://t.me/{ch}/{msg.id}"

            media: Optional[Dict[str, Any]] = None
            if msg.media:
                media = {"type": msg.media.__class__.__name__}

            raw = {
                "id": msg.id,
                "date": msg_dt.isoformat(),
                "text": text,
                "views": views,
                "forwards": forwards,
                "replies": replies,
                "has_media": bool(msg.media),
            }

            yield CollectedMessage(
                source="telegram",
                channel=ch,
                message_id=msg.id,
                date_utc=msg_dt.astimezone(timezone.utc),
                text=text,
                views=views,
                forwards=forwards,
                replies=replies,
                permalink=permalink,
                media=media,
                raw=raw,
            )

            fetched += 1
            # Safety: Telethon already paginates, but we keep our own guard
            if limit is not None and fetched >= limit:
                break
