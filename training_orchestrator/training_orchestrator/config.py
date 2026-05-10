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
    command_timeout: int = 60

    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class ServiceConfig(BaseModel):
    poll_interval_seconds: float = 5.0
    max_jobs_per_tick: int = 1


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8040


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    service_name: str = "training-orchestrator"
    postgres: PostgresConfig = PostgresConfig()
    service: ServiceConfig = ServiceConfig()
    api: ApiConfig = ApiConfig()
    logging: LoggingConfig = LoggingConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRAINING_ORCHESTRATOR__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    service: Optional[ServiceConfig] = None
    api: Optional[ApiConfig] = None
    logging: Optional[LoggingConfig] = None


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: Path) -> AppConfig:
    data: Dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    file_config = AppConfig.model_validate(data)
    env_config = EnvConfig().model_dump(exclude_none=True)
    return AppConfig.model_validate(_deep_update(file_config.model_dump(), env_config))
