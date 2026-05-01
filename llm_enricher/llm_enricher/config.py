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
    port: int = 8001


class HealthConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class LoggingConfig(BaseModel):
    level: str = "INFO"


class CacheConfig(BaseModel):
    ttl_seconds: int = 604800  # 7 days
    error_ttl_seconds: int = 300  # 5 minutes


class BudgetConfig(BaseModel):
    daily_usd: float = 5.0
    # Mistral pricing in USD per 1M tokens (overridable via env)
    pricing_input_per_mtok: float = 2.0
    pricing_output_per_mtok: float = 6.0


class CircuitBreakerConfig(BaseModel):
    fail_max: int = 5
    reset_timeout_seconds: int = 30


class LLMConfig(BaseModel):
    provider: str = "mock"
    model_name: str = "mistral-large-latest"
    max_tokens_summary: int = 500
    max_tokens_explanation: int = 600
    max_tokens_novelty: int = 300
    max_tokens_label: int = 100
    temperature: float = 0.2
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()


class AppConfig(BaseModel):
    service_name: str = "llm-enricher"
    postgres: PostgresConfig = PostgresConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    logging: LoggingConfig = LoggingConfig()
    cache: CacheConfig = CacheConfig()
    budget: BudgetConfig = BudgetConfig()
    llm: LLMConfig = LLMConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_ENRICHER__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    metrics: Optional[MetricsConfig] = None
    health: Optional[HealthConfig] = None
    logging: Optional[LoggingConfig] = None
    cache: Optional[CacheConfig] = None
    budget: Optional[BudgetConfig] = None
    llm: Optional[LLMConfig] = None


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
