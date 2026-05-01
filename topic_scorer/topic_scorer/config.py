from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, field_validator
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
    port: int = 8005


class LoggingConfig(BaseModel):
    level: str = "INFO"


class ScoringWeightsConfig(BaseModel):
    growth_rate: float = 0.22
    message_count: float = 0.12
    unique_channels: float = 0.14
    new_channel_ratio: float = 0.08
    unique_entities: float = 0.10
    novelty: float = 0.10
    sentiment_intensity: float = 0.10
    sentiment_shift: float = 0.06
    cluster_density: float = 0.08

    @field_validator("*", mode="before")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("weight must be >= 0")
        return v


class LevelThresholdsConfig(BaseModel):
    low: float = 0.0
    medium: float = 0.35
    high: float = 0.65
    critical: float = 0.85


class ScoringConfig(BaseModel):
    version: str = "v1"
    weights: ScoringWeightsConfig = ScoringWeightsConfig()
    level_thresholds: LevelThresholdsConfig = LevelThresholdsConfig()

    # Small-cluster handling: if message_count < threshold, apply penalty factor
    min_messages_for_full_score: int = 3
    small_cluster_penalty: float = 0.5

    # History window for novelty / new-channel ratio comparison (days)
    history_window_days: int = 14

    # Sub-window split for growth_rate and sentiment_shift (fraction of total window)
    growth_split_fraction: float = 0.5

    # Noise epsilon for division-safe operations
    epsilon: float = 1e-6


class SchedulerConfig(BaseModel):
    # Interval in seconds for scheduled (periodic) mode
    interval_seconds: int = 300


class AppConfig(BaseModel):
    service_name: str = "topic-scorer"
    postgres: PostgresConfig = PostgresConfig()
    metrics: MetricsConfig = MetricsConfig()
    logging: LoggingConfig = LoggingConfig()
    scoring: ScoringConfig = ScoringConfig()
    scheduler: SchedulerConfig = SchedulerConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOPIC_SCORER__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    metrics: Optional[MetricsConfig] = None
    logging: Optional[LoggingConfig] = None
    scoring: Optional[ScoringConfig] = None
    scheduler: Optional[SchedulerConfig] = None


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
