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
    max_size: int = 3
    command_timeout: int = 300

    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class BenchmarkConfig(BaseModel):
    default_models: list[str] = ["sbert_umap_hdbscan", "lda", "nmf"]
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    max_messages: int = 2500
    min_messages: int = 30
    top_words: int = 12
    n_topics: int = 12
    seed: int = 42
    use_gpu: bool = False
    worker_poll_interval_seconds: int = 15


class AppConfig(BaseModel):
    service_name: str = "topic-benchmark-runner"
    postgres: PostgresConfig = PostgresConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOPIC_BENCHMARK__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    postgres: Optional[PostgresConfig] = None
    benchmark: Optional[BenchmarkConfig] = None


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
    return AppConfig.model_validate(_deep_update(file_config.model_dump(), env_config))
