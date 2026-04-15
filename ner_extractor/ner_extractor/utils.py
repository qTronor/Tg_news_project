from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def decode_kafka_key(key: Optional[bytes]) -> Optional[str]:
    if key is None:
        return None
    if isinstance(key, bytes):
        return key.decode("utf-8")
    return str(key)


def parse_iso_datetime(value: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"invalid datetime value: {value!r}")
    cleaned = value
    if value.endswith("Z"):
        cleaned = value[:-1] + "+00:00"
    return datetime.fromisoformat(cleaned)


def parse_optional_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return parse_iso_datetime(value)
