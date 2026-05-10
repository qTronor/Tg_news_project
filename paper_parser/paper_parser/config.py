from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "paper-parser-group"
    input_topic: str = "paper.detected"
    output_topic: str = "paper.parsed"
    dlq_topic: str = "dlq.paper"
    auto_offset_reset: str = "latest"


class PostgresConfig(BaseModel):
    dsn: str = "postgresql://postgres:password@localhost:5432/telegram_news"
    min_size: int = 2
    max_size: int = 10
    command_timeout: int = 60


class ServiceConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8062
    metrics_port: int = 8063
    log_level: str = "INFO"
    http_timeout_seconds: int = 30
    max_full_text_chars: int = 100000
    summary_text_chars: int = 8000


class AppConfig(BaseModel):
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    service: ServiceConfig = ServiceConfig()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if dsn := os.getenv("POSTGRES_DSN"):
            data.setdefault("postgres", {})["dsn"] = dsn
        if servers := os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
            data.setdefault("kafka", {})["bootstrap_servers"] = servers
        return cls(**data)
