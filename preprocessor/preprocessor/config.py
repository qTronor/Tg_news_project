from __future__ import annotations

from pathlib import Path
from typing import Optional, Any, Dict, List

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    input_topics: List[str] = ["raw.telegram.messages", "persisted.messages"]
    output_topic: str = "preprocessed.messages"
    dlq_topic: str = "dlq.preprocessing"
    consumer_group: str = "preprocessor-group"
    client_id: str = "preprocessor"
    max_poll_records: int = 50
    poll_timeout_ms: int = 1000
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
    port: int = 8011


class HealthConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8010


class SchemaConfig(BaseModel):
    raw_message_path: Path = Path("schemas/raw_message.schema.json")
    persisted_message_path: Path = Path("schemas/persisted_message.schema.json")
    preprocessed_message_path: Path = Path("schemas/preprocessed_message.schema.json")


class PreprocessingConfig(BaseModel):
    version: str = "1.0.0"


class LanguageDetectionConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.55
    full_analysis_languages: List[str] = ["ru", "en"]
    unsupported_analysis_mode: str = "partial"
    unknown_analysis_mode: str = "unknown"
    backend: str = "fasttext"
    fasttext_model_path: Path = Path("/app/models/lid.176.bin")
    auto_download: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    service_name: str = "preprocessor"
    consumer_id: str = "preprocessor"
    source_system: str = "preprocessor"
    event_version: str = "v1.0.0"
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    retry: RetryConfig = RetryConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    schemas: SchemaConfig = SchemaConfig()
    preprocessing: PreprocessingConfig = PreprocessingConfig()
    language_detection: LanguageDetectionConfig = LanguageDetectionConfig()
    logging: LoggingConfig = LoggingConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PREPROCESSOR__",
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
    preprocessing: Optional[PreprocessingConfig] = None
    language_detection: Optional[LanguageDetectionConfig] = None
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
