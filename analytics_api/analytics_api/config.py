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


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8020
    default_window_hours: int = 24
    default_documents_limit: int = 50
    max_documents_limit: int = 200
    default_graph_nodes: int = 30
    max_graph_nodes: int = 120
    graph_metrics_cache_ttl_seconds: int = 900
    topic_comparison_cache_ttl_seconds: int = 900


class MetricsConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8021


class HealthConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8020


class LoggingConfig(BaseModel):
    level: str = "INFO"


class LLMEnricherClientConfig(BaseModel):
    url: str = "http://localhost:8030"
    timeout_seconds: float = 2.0
    refresh_timeout_seconds: float = 30.0
    enabled: bool = True


class AppConfig(BaseModel):
    service_name: str = "analytics-api"
    postgres: PostgresConfig = PostgresConfig()
    api: ApiConfig = ApiConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    logging: LoggingConfig = LoggingConfig()
    llm_enricher: LLMEnricherClientConfig = LLMEnricherClientConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_API__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    api: Optional[ApiConfig] = None
    metrics: Optional[MetricsConfig] = None
    health: Optional[HealthConfig] = None
    logging: Optional[LoggingConfig] = None
    llm_enricher: Optional[LLMEnricherClientConfig] = None


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
