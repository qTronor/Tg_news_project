from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str = "telegram_news"
    user: str = "postgres"
    password: str = "postgres"
    min_size: int = 1
    max_size: int = 5
    command_timeout: int = 30

    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


class MetricsConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8041


class HealthConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8040


class SchedulerConfig(BaseModel):
    interval_seconds: int = 300
    cluster_batch_size: int = 20


class LoggingConfig(BaseModel):
    level: str = "INFO"


class ResolutionConfig(BaseModel):
    inferred_threshold: float = 0.55
    earliest_cluster_confidence: float = 0.35
    quote_min_chars: int = 20


class AppConfig(BaseModel):
    service_name: str = "source-resolver"
    postgres: PostgresConfig = PostgresConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    logging: LoggingConfig = LoggingConfig()
    resolution: ResolutionConfig = ResolutionConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SOURCE_RESOLVER__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    metrics: Optional[MetricsConfig] = None
    health: Optional[HealthConfig] = None
    scheduler: Optional[SchedulerConfig] = None
    logging: Optional[LoggingConfig] = None
    resolution: Optional[ResolutionConfig] = None


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Path) -> AppConfig:
    data: Dict[str, Any] = {}
    if path and path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    file_config = AppConfig.model_validate(data)
    env_config = EnvConfig().model_dump(exclude_none=True)
    merged = _deep_update(file_config.model_dump(), env_config)
    return AppConfig.model_validate(merged)
