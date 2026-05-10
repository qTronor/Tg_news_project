from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, Optional

from telethon import TelegramClient, utils
from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    RPCError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Message

from collector.models import CollectedMessage
from collector.sources.base import Source


@dataclass(frozen=True)
class TelegramProxySettings:
    enabled: bool = False
    scheme: str = "socks5"
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    rdns: bool = True


@dataclass(frozen=True)
class ValidatedTelegramChannel:
    name: str
    url: str
    channel_id: int
    title: Optional[str]
    description: Optional[str]
    subscriber_count: Optional[int]


@dataclass(frozen=True)
class TelegramChannelError(Exception):
    reason: str
    message: str
    retry_after_seconds: Optional[int] = None
    permanent: bool = False


def _env_required(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_proxy_settings(proxy: Optional[TelegramProxySettings]) -> TelegramProxySettings:
    base = proxy or TelegramProxySettings()

    enabled = base.enabled
    if os.getenv("TG_PROXY_ENABLED") is not None:
        enabled = _env_flag("TG_PROXY_ENABLED", default=base.enabled)

    scheme = (os.getenv("TG_PROXY_SCHEME") or base.scheme or "socks5").strip().lower()
    host = os.getenv("TG_PROXY_HOST")
    if host is None:
        host = base.host

    port_env = os.getenv("TG_PROXY_PORT")
    port = int(port_env) if port_env else base.port

    username = os.getenv("TG_PROXY_USERNAME")
    if username is None:
        username = base.username
    username = username or None

    password = os.getenv("TG_PROXY_PASSWORD")
    if password is None:
        password = base.password
    password = password or None

    rdns = base.rdns
    if os.getenv("TG_PROXY_RDNS") is not None:
        rdns = _env_flag("TG_PROXY_RDNS", default=base.rdns)

    return TelegramProxySettings(
        enabled=enabled,
        scheme=scheme,
        host=host,
        port=port,
        username=username,
        password=password,
        rdns=rdns,
    )


def _build_telethon_proxy(proxy: TelegramProxySettings) -> Any:
    if not proxy.enabled:
        return None
    if not proxy.host or not proxy.port:
        raise RuntimeError("Telegram proxy is enabled, but TG_PROXY_HOST or TG_PROXY_PORT is missing.")
    proxy_type = proxy.scheme.lower()
    if proxy_type not in {"socks5", "socks4", "http"}:
        raise RuntimeError(
            f"Unsupported Telegram proxy scheme: {proxy.scheme}. Expected one of: socks5, socks4, http."
        )

    return (
        proxy_type,
        proxy.host,
        proxy.port,
        proxy.rdns,
        proxy.username,
        proxy.password,
    )


def _coerce_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _peer_id(peer: Any) -> Optional[int]:
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


def _normalize_channel_reference(channel: str) -> str:
    value = channel.strip()
    if value.startswith("https://t.me/"):
        value = value.replace("https://t.me/", "", 1)
    elif value.startswith("http://t.me/"):
        value = value.replace("http://t.me/", "", 1)
    if value.startswith("@"):
        value = value[1:]
    return value.strip("/")


def classify_telegram_exception(exc: Exception) -> TelegramChannelError:
    if isinstance(exc, TelegramChannelError):
        return exc
    if isinstance(exc, FloodWaitError):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return TelegramChannelError(
            reason="flood_wait",
            message=f"Telegram flood wait for {seconds} seconds.",
            retry_after_seconds=seconds,
            permanent=False,
        )
    if isinstance(exc, (UsernameInvalidError, InviteHashExpiredError, ChannelInvalidError)):
        return TelegramChannelError(
            reason="not_found",
            message="Telegram channel not found.",
            permanent=True,
        )
    if isinstance(exc, (UsernameNotOccupiedError, ValueError)):
        return TelegramChannelError(
            reason="not_found",
            message="Telegram channel not found.",
            permanent=True,
        )
    if isinstance(exc, ChannelPrivateError):
        return TelegramChannelError(
            reason="private",
            message="Telegram channel is private or inaccessible.",
            permanent=True,
        )
    if isinstance(exc, RPCError):
        return TelegramChannelError(
            reason="inaccessible",
            message=str(exc),
            permanent=False,
        )
    return TelegramChannelError(
        reason="inaccessible",
        message=str(exc),
        permanent=False,
    )


class TelegramChannelSource(Source):
    def __init__(
        self,
        *,
        session_name: str = "telegram",
        workdir: str = ".",
        proxy: Optional[TelegramProxySettings] = None,
    ):
        api_id = int(_env_required("TG_API_ID"))
        api_hash = _env_required("TG_API_HASH")

        string_session = os.getenv("TG_STRING_SESSION")
        if string_session:
            session = StringSession(string_session)
        else:
            session = session_name
        proxy_settings = _load_proxy_settings(proxy)

        self.client = TelegramClient(
            session,
            api_id,
            api_hash,
            device_model="collector",
            system_version="1.0",
            proxy=_build_telethon_proxy(proxy_settings),
        )
        self.workdir = workdir

    async def __aenter__(self):
        await self.client.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.disconnect()

    async def validate_channel(self, channel: str) -> ValidatedTelegramChannel:
        ch = _normalize_channel_reference(channel)
        try:
            entity = await self.client.get_entity(ch)
            if not isinstance(entity, types.Channel):
                raise TelegramChannelError(
                    reason="inaccessible",
                    message="Only Telegram channels are supported.",
                    permanent=True,
                )

            username = getattr(entity, "username", None)
            if not username:
                raise TelegramChannelError(
                    reason="private",
                    message="Private Telegram channels are not supported.",
                    permanent=True,
                )

            full = await self.client(GetFullChannelRequest(entity))
            full_chat = getattr(full, "full_chat", None)
            return ValidatedTelegramChannel(
                name=username,
                url=f"https://t.me/{username}",
                channel_id=utils.get_peer_id(entity, add_mark=False),
                title=getattr(entity, "title", None),
                description=getattr(full_chat, "about", None),
                subscriber_count=getattr(full_chat, "participants_count", None),
            )
        except Exception as exc:
            raise classify_telegram_exception(exc) from exc

    async def iter_messages(
        self,
        channel: str,
        since: Optional[date],
        min_id_exclusive: Optional[int],
        limit: Optional[int],
    ) -> AsyncIterator[CollectedMessage]:
        ch = _normalize_channel_reference(channel)
        since_dt_utc: Optional[datetime] = None
        if since:
            since_dt_utc = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)

        iter_params = {
            "reverse": False,
            "limit": limit,
        }
        if min_id_exclusive:
            iter_params["min_id"] = min_id_exclusive

        fetched = 0
        try:
            async for msg in self.client.iter_messages(ch, **iter_params):
                item = self._message_to_item(ch, msg)
                if item is None:
                    continue
                if since_dt_utc and item.date_utc < since_dt_utc:
                    break
                yield item
                fetched += 1
                if limit is not None and fetched >= limit:
                    break
        except Exception as exc:
            raise classify_telegram_exception(exc) from exc

    async def iter_messages_in_date_range(
        self,
        channel: str,
        *,
        start_date: date,
        end_date_exclusive: date,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CollectedMessage]:
        ch = _normalize_channel_reference(channel)
        start_dt_utc = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end_dt_utc = datetime(
            end_date_exclusive.year,
            end_date_exclusive.month,
            end_date_exclusive.day,
            tzinfo=timezone.utc,
        )
        fetched = 0
        try:
            async for msg in self.client.iter_messages(
                ch,
                reverse=False,
                offset_date=end_dt_utc,
                limit=limit,
            ):
                item = self._message_to_item(ch, msg)
                if item is None:
                    continue
                if item.date_utc >= end_dt_utc:
                    continue
                if item.date_utc < start_dt_utc:
                    break
                yield item
                fetched += 1
                if limit is not None and fetched >= limit:
                    break
        except Exception as exc:
            raise classify_telegram_exception(exc) from exc

    async def iter_messages_for_day(
        self,
        channel: str,
        *,
        day: date,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CollectedMessage]:
        async for item in self.iter_messages_in_date_range(
            channel,
            start_date=day,
            end_date_exclusive=day + timedelta(days=1),
            limit=limit,
        ):
            yield item

    def _message_to_item(self, channel_name: str, msg: Message) -> Optional[CollectedMessage]:
        if not isinstance(msg, Message):
            return None
        if not msg.date:
            return None

        msg_dt = _coerce_utc(msg.date)
        if msg_dt is None:
            return None

        text = (msg.message or "").strip()
        if not text:
            return None
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
        permalink = f"https://t.me/{channel_name}/{msg.id}"

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

        return CollectedMessage(
            source="telegram",
            channel=channel_name,
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
