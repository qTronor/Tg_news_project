from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    input_topic: str = "preprocessed.messages"
    output_topic: str = "sentiment.enriched"
    dlq_topic: str = "dlq.sentiment"
    consumer_group: str = "sentiment-analyzer-group"
    client_id: str = "sentiment-analyzer"
    max_poll_records: int = 50
    auto_offset_reset: str = "earliest"
    session_timeout_ms: int = 10000
    request_timeout_ms: int = 30000
    max_partition_fetch_bytes: int = 10485760


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


class RetryConfig(BaseModel):
    max_attempts: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0
    backoff_multiplier: float = 2.0


class MetricsConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8001


class HealthConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class SchemaConfig(BaseModel):
    preprocessed_message_path: Path = Path("schemas/preprocessed_message.schema.json")
    sentiment_enriched_path: Path = Path("schemas/sentiment_enriched.schema.json")


class LoggingConfig(BaseModel):
    level: str = "INFO"


class ModelConfig(BaseModel):
    name: str = "blanchefort/rubert-base-cased-sentiment"
    local_path: Optional[str] = None
    label2id_path: Optional[str] = None
    device: str = "cpu"
    batch_size: int = 32
    max_length: int = 384
    chunk_overlap: int = 64
    neutral_threshold: float = 0.55
    version: str = "1.0.0"


class AppConfig(BaseModel):
    service_name: str = "sentiment-analyzer"
    consumer_id: str = "sentiment-analyzer"
    source_system: str = "sentiment-analyzer"
    event_version: str = "v1.0.0"
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    retry: RetryConfig = RetryConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    schemas: SchemaConfig = SchemaConfig()
    logging: LoggingConfig = LoggingConfig()
    model: ModelConfig = ModelConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTIMENT_ANALYZER__",
        env_nested_delimiter="__",
        extra="ignore",
    )

    service_name: Optional[str] = None
    consumer_id: Optional[str] = None
    source_system: Optional[str] = None
    event_version: Optional[str] = None
    kafka: Optional[KafkaConfig] = None
    postgres: Optional[PostgresConfig] = None
    retry: Optional[RetryConfig] = None
    metrics: Optional[MetricsConfig] = None
    health: Optional[HealthConfig] = None
    schemas: Optional[SchemaConfig] = None
    logging: Optional[LoggingConfig] = None
    model: Optional[ModelConfig] = None


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
