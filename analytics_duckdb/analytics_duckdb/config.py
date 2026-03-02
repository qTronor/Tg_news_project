from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DuckDBConfig(BaseModel):
    threads: Optional[int] = None
    memory_limit: Optional[str] = None


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8020


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    service_name: str = "analytics-duckdb"
    lake_path: Path = Path("lake")
    duckdb: DuckDBConfig = DuckDBConfig()
    api: ApiConfig = ApiConfig()
    logging: LoggingConfig = LoggingConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_DUCKDB__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    lake_path: Optional[Path] = None
    duckdb: Optional[DuckDBConfig] = None
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
    if path and path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    file_config = AppConfig.model_validate(data)
    env_config = EnvConfig().model_dump(exclude_none=True)
    merged = _deep_update(file_config.model_dump(), env_config)
    return AppConfig.model_validate(merged)
