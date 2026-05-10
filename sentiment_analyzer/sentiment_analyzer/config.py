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


class SentimentModelConfig(BaseModel):
    """Config for one HF sentiment classification model."""

    name: str = "cointegrated/rubert-tiny-sentiment-balanced"
    local_path: Optional[str] = None
    cache_dir: Optional[str] = None
    device: str = "auto"
    use_float16: bool = True
    batch_size: int = 32
    max_length: int = 384
    chunk_overlap: int = 64
    neutral_threshold: float = 0.55
    version: str = "1.0.0"


class EmotionModelConfig(BaseModel):
    """Config for one HF emotion classification model."""

    name: str = ""
    version: str = "1.0.0"
    device: str = "auto"
    use_float16: bool = True
    batch_size: int = 32
    max_length: int = 128
    cache_dir: Optional[str] = None
    enabled: bool = True


class ModelsConfig(BaseModel):
    """Per-language model routing config replacing the old single-model ModelConfig."""

    # RU sentiment: rubert-tiny-sentiment-balanced (default) or blanchefort
    ru: SentimentModelConfig = SentimentModelConfig(
        name="cointegrated/rubert-tiny-sentiment-balanced",
        version="1.0.0",
    )
    # EN / other supported languages → multilingual XLM-R
    multilingual: SentimentModelConfig = SentimentModelConfig(
        name="cardiffnlp/twitter-xlm-roberta-base-sentiment",
        version="1.0.0",
        max_length=512,
        chunk_overlap=64,
        neutral_threshold=0.50,
    )
    # RU emotion: rubert-tiny2-cedr (joy/sadness/surprise/fear/anger)
    emotion_ru: EmotionModelConfig = EmotionModelConfig(
        name="cointegrated/rubert-tiny2-cedr-emotion-detection",
        version="1.0.0",
        enabled=True,
    )
    # EN emotion: distilroberta + disgust label
    emotion_en: EmotionModelConfig = EmotionModelConfig(
        name="j-hartmann/emotion-english-distilroberta-base",
        version="1.0.0",
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Backward-compat alias: old config.yaml may still have a top-level `model:`
# block. We keep ModelConfig as a thin alias so EnvConfig can still accept it,
# but AppConfig now uses `models: ModelsConfig`.
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    """Legacy single-model config. Only used when reading old YAML; service
    now reads from AppConfig.models instead."""

    name: str = "cointegrated/rubert-tiny-sentiment-balanced"
    local_path: Optional[str] = None
    label2id_path: Optional[str] = None
    cache_dir: Optional[str] = None
    device: str = "auto"
    use_float16: bool = True
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
    models: ModelsConfig = ModelsConfig()


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
    models: Optional[ModelsConfig] = None


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _migrate_legacy_model_key(data: Dict[str, Any]) -> Dict[str, Any]:
    """If YAML has the old ``model:`` key, promote it into ``models.ru``."""
    if "model" in data and "models" not in data:
        old = data.pop("model")
        # Treat old single-model config as the RU backend.
        data["models"] = {"ru": old}
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
