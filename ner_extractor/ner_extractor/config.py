from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    input_topic: str = "preprocessed.messages"
    output_topic: str = "ner.enriched"
    dlq_topic: str = "dlq.ner"
    consumer_group: str = "ner-extractor-group"
    client_id: str = "ner-extractor"
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
    ner_enriched_path: Path = Path("schemas/ner_enriched.schema.json")


class LoggingConfig(BaseModel):
    level: str = "INFO"


class NatashaModelConfig(BaseModel):
    """Config for the Natasha (RU) NER backend."""

    version: str = "1.0.0"
    confidence: float = 0.8
    min_entity_length: int = 3


class TransformersModelConfig(BaseModel):
    """Config for the transformers (EN) NER backend."""

    name: str = "dslim/bert-base-NER"
    version: str = "1.0.0"
    device: str = "auto"
    batch_size: int = 8
    min_entity_length: int = 2
    confidence_threshold: float = 0.80
    cache_dir: Optional[str] = None
    enabled: bool = True


class ModelsConfig(BaseModel):
    """Per-language NER model config."""

    ru: NatashaModelConfig = NatashaModelConfig()
    en: TransformersModelConfig = TransformersModelConfig()


# Backward-compat alias
class ModelConfig(BaseModel):
    """Legacy flat model config. Kept so old YAML doesn't crash on load."""

    confidence: float = 0.8
    min_entity_length: int = 3
    version: str = "1.0.0"


class AppConfig(BaseModel):
    service_name: str = "ner-extractor"
    consumer_id: str = "ner-extractor"
    source_system: str = "ner-extractor"
    event_version: str = "v1.0.0"
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    retry: RetryConfig = RetryConfig()
    metrics: MetricsConfig = MetricsConfig()
    health: HealthConfig = HealthConfig()
    schemas: SchemaConfig = SchemaConfig()
    logging: LoggingConfig = LoggingConfig()
    models: ModelsConfig = ModelsConfig()


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NER_EXTRACTOR__",
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
    models: Optional[ModelsConfig] = None


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _migrate_legacy_model_key(data: Dict[str, Any]) -> Dict[str, Any]:
    """If YAML has the old flat ``model:`` key, promote it into ``models.ru``."""
    if "model" in data and "models" not in data:
        old = data.pop("model")
        data["models"] = {
            "ru": {
                "version": old.get("version", "1.0.0"),
                "confidence": old.get("confidence", 0.8),
                "min_entity_length": old.get("min_entity_length", 3),
            }
        }
    return data


def load_config(path: Path) -> AppConfig:
    data: Dict[str, Any] = {}
    if path and path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _migrate_legacy_model_key(data)
    file_config = AppConfig.model_validate(data)
    env_config = EnvConfig().model_dump(exclude_none=True)
    merged = _deep_update(file_config.model_dump(), env_config)
    return AppConfig.model_validate(merged)
