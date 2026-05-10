from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "paper-summarizer-group"
    input_topic: str = "paper.parsed"
    output_topic: str = "paper.summarized"
    dlq_topic: str = "dlq.paper"
    auto_offset_reset: str = "latest"


class PostgresConfig(BaseModel):
    dsn: str = "postgresql://postgres:password@localhost:5432/telegram_news"
    min_size: int = 2
    max_size: int = 10
    command_timeout: int = 30


class MistralConfig(BaseModel):
    api_key: str = ""
    model: str = "mistral-small-latest"
    base_url: str = "https://api.mistral.ai/v1"
    timeout_seconds: int = 60
    max_retries: int = 3


class ServiceConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8064
    metrics_port: int = 8065
    log_level: str = "INFO"


class AppConfig(BaseModel):
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    mistral: MistralConfig = MistralConfig()
    service: ServiceConfig = ServiceConfig()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if dsn := os.getenv("POSTGRES_DSN"):
            data.setdefault("postgres", {})["dsn"] = dsn
        if servers := os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
            data.setdefault("kafka", {})["bootstrap_servers"] = servers
        if key := os.getenv("MISTRAL_API_KEY"):
            data.setdefault("mistral", {})["api_key"] = key
        if model := os.getenv("MISTRAL_MODEL"):
            data.setdefault("mistral", {})["model"] = model
        return cls(**data)
