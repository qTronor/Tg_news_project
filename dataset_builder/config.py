from __future__ import annotations

import os

import yaml
from pydantic import BaseModel, Field


class PostgresConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    dbname: str = "telegram_news"
    min_size: int = 2
    max_size: int = 10
    command_timeout: float = 30.0

    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


class BuilderConfig(BaseModel):
    min_word_count: int = 5
    max_word_count: int = 2000
    supported_languages: list[str] = Field(default_factory=lambda: ["ru", "en"])
    dedup_strategy: str = "event_id"
    train_ratio: float = 0.70
    validation_ratio: float = 0.15
    test_ratio: float = 0.10
    temporal_test_ratio: float = 0.05


class AppConfig(BaseModel):
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    builder: BuilderConfig = Field(default_factory=BuilderConfig)


def load_config(path: str = "config.yaml") -> AppConfig:
    raw: dict = {}
    if os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

    pg_data: dict = raw.get("postgres", {})
    pg_data["password"] = os.environ.get("DB_PASSWORD", pg_data.get("password", ""))

    return AppConfig(
        postgres=PostgresConfig(**pg_data),
        builder=BuilderConfig(**raw.get("builder", {})),
    )
