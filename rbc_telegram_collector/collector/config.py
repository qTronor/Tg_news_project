from __future__ import annotations

import os
from datetime import date
from typing import List, Literal, Optional
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


class TelegramProxyConfig(BaseModel):
    enabled: bool = Field(default_factory=lambda: (os.getenv("TG_PROXY_ENABLED") or "").lower() in {"1", "true", "yes", "on"})
    scheme: Literal["socks5", "socks4", "http"] = Field(
        default_factory=lambda: (os.getenv("TG_PROXY_SCHEME") or "socks5").lower()
    )
    host: Optional[str] = Field(default_factory=lambda: os.getenv("TG_PROXY_HOST"))
    port: Optional[int] = Field(
        default_factory=lambda: int(os.getenv("TG_PROXY_PORT")) if os.getenv("TG_PROXY_PORT") else None
    )
    username: Optional[str] = Field(default_factory=lambda: os.getenv("TG_PROXY_USERNAME"))
    password: Optional[str] = Field(default_factory=lambda: os.getenv("TG_PROXY_PASSWORD"))
    rdns: bool = Field(default_factory=lambda: (os.getenv("TG_PROXY_RDNS") or "true").lower() not in {"0", "false", "no", "off"})


class TelegramConfig(BaseModel):
    proxy: TelegramProxyConfig = TelegramProxyConfig()


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


class AnalyticsDbConfig(BaseModel):
    enabled: bool = False
    host: str = Field(default_factory=lambda: os.getenv("COLLECTOR_ANALYTICS_DB_HOST") or "localhost")
    port: int = Field(default_factory=lambda: int(os.getenv("COLLECTOR_ANALYTICS_DB_PORT") or "5432"))
    database: str = Field(default_factory=lambda: os.getenv("COLLECTOR_ANALYTICS_DB_NAME") or "telegram_news")
    user: str = Field(default_factory=lambda: os.getenv("COLLECTOR_ANALYTICS_DB_USER") or "postgres")
    password: str = Field(default_factory=lambda: os.getenv("COLLECTOR_ANALYTICS_DB_PASSWORD") or "postgres")
    schema: Optional[str] = Field(default_factory=lambda: os.getenv("COLLECTOR_ANALYTICS_DB_SCHEMA"))
    min_size: int = 1
    max_size: int = 5
    command_timeout: int = 30

    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class SchedulerConfig(BaseModel):
    enabled: bool = False
    interval_seconds: int = Field(default=3600, ge=1)


class BackfillConfig(BaseModel):
    enabled: bool = True
    global_concurrency: int = Field(default=1, ge=1)
    max_jobs_per_cycle: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    retry_backoff_seconds: int = Field(default=60, ge=1)
    flood_sleep_cap_seconds: int = Field(default=300, ge=1)


class AppConfig(BaseModel):
    channels: List[ChannelConfig]
    telegram: TelegramConfig = TelegramConfig()
    output: OutputConfig = OutputConfig()
    logging: LoggingConfig = LoggingConfig()
    collection: CollectionConfig = CollectionConfig()
    kafka: KafkaConfig = KafkaConfig()
    analytics_db: AnalyticsDbConfig = AnalyticsDbConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    backfill: BackfillConfig = BackfillConfig()
