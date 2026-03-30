from __future__ import annotations

import os
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


class CollectionConfig(BaseModel):
    lookback_days: int = Field(default=3, ge=1)


class KafkaConfig(BaseModel):
    enabled: bool = True
    bootstrap_servers: str = Field(
        default_factory=lambda: (
            os.getenv("COLLECTOR_KAFKA_BOOTSTRAP_SERVERS")
            or os.getenv("KAFKA_BOOTSTRAP_SERVERS")
            or "localhost:9092"
        )
    )
    topic: str = "raw.telegram.messages"
    client_id: str = "telegram-collector"


class SchedulerConfig(BaseModel):
    enabled: bool = False
    interval_seconds: int = Field(default=3600, ge=1)


class AppConfig(BaseModel):
    channels: List[ChannelConfig]
    output: OutputConfig = OutputConfig()
    logging: LoggingConfig = LoggingConfig()
    collection: CollectionConfig = CollectionConfig()
    kafka: KafkaConfig = KafkaConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
