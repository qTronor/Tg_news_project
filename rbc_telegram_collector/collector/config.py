from __future__ import annotations

from datetime import date
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, HttpUrl


class ChannelConfig(BaseModel):
    name: str = Field(..., description="Username without @, e.g. rbc_news")
    url: Optional[HttpUrl] = None
    enabled: bool = True
    since: Optional[date] = None
    limit: Optional[int] = 2000


class OutputConfig(BaseModel):
    data_dir: str = "data"
    state_dir: str = "state"
    formats: List[Literal["jsonl", "csv"]] = ["jsonl"]


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    channels: List[ChannelConfig]
    output: OutputConfig = OutputConfig()
    logging: LoggingConfig = LoggingConfig()
