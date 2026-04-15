from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse


HISTORICAL_LOWER_BOUND = date(2026, 1, 1)
PUBLIC_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
PUBLIC_HOSTS = {
    "t.me",
    "www.t.me",
    "telegram.me",
    "www.telegram.me",
}


@dataclass(slots=True)
class SourceRegistryError(Exception):
    error_type: str
    message: str
    status_code: int = 400
    meta: dict[str, Any] | None = None


def normalize_telegram_channel_input(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise SourceRegistryError(
            error_type="invalid_link_or_username",
            message="Telegram public username or link is required.",
            status_code=422,
        )

    username = _extract_username(value)
    if not PUBLIC_USERNAME_RE.fullmatch(username):
        raise SourceRegistryError(
            error_type="invalid_link_or_username",
            message="Only public Telegram channel usernames are supported.",
            status_code=422,
        )

    return username


def normalize_requested_start_date(
    requested_start_date: date,
    *,
    today: date | None = None,
) -> date:
    if requested_start_date < HISTORICAL_LOWER_BOUND:
        raise SourceRegistryError(
            error_type="date_before_limit",
            message="Historical lower bound is 2026-01-01.",
            status_code=422,
            meta={"historical_limit_date": HISTORICAL_LOWER_BOUND.isoformat()},
        )

    current_day = today or datetime.now(timezone.utc).date()
    return min(requested_start_date, current_day)


def derive_channel_status(row: dict[str, Any]) -> str:
    validation_status = row["validation_status"]
    registry_status = row["registry_status"]
    pending_days = int(row["backfill_pending_days"] or 0)
    running_days = int(row["backfill_running_days"] or 0)
    retrying_days = int(row["backfill_retrying_days"] or 0)

    if validation_status == "pending" or registry_status == "pending_validation":
        return "validating"
    if validation_status == "failed" or registry_status == "validation_failed":
        return "validation_failed"
    if pending_days > 0 or running_days > 0 or retrying_days > 0 or registry_status == "backfilling":
        return "backfilling"
    if registry_status == "live_enabled":
        return "live_enabled"
    return "ready"


def build_feed_path(channel_name: str, first_message_available: bool) -> str | None:
    if not first_message_available:
        return None
    return f"/feed?channel={channel_name}"


def _extract_username(value: str) -> str:
    if value.startswith("@"):
        return value[1:]

    if value.lower().startswith("t.me/") or value.lower().startswith("telegram.me/"):
        value = f"https://{value}"

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = parsed.netloc.lower()
        if host not in PUBLIC_HOSTS:
            raise SourceRegistryError(
                error_type="invalid_link_or_username",
                message="Unsupported Telegram link host.",
                status_code=422,
            )

        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            raise SourceRegistryError(
                error_type="invalid_link_or_username",
                message="Telegram link must include a public channel username.",
                status_code=422,
            )
        if segments[0] == "s" and len(segments) >= 2:
            return segments[1]
        if segments[0] in {"joinchat", "c"} or segments[0].startswith("+"):
            raise SourceRegistryError(
                error_type="invalid_link_or_username",
                message="Private or invite-only Telegram links are not supported.",
                status_code=422,
            )
        if len(segments) > 1:
            raise SourceRegistryError(
                error_type="invalid_link_or_username",
                message="Telegram message links are not supported here; use the public channel link.",
                status_code=422,
            )
        return segments[0]

    return value
