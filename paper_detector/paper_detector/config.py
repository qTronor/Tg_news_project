from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9092"
    consumer_group: str = "paper-detector-group"
    input_topic: str = "preprocessed.messages"
    output_topic: str = "paper.detected"
    dlq_topic: str = "dlq.paper"
    auto_offset_reset: str = "latest"
    max_poll_records: int = 50


class PostgresConfig(BaseModel):
    dsn: str = "postgresql://postgres:password@localhost:5432/telegram_news"
    min_size: int = 2
    max_size: int = 10
    command_timeout: int = 30


class ServiceConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8060
    metrics_port: int = 8061
    log_level: str = "INFO"


class AppConfig(BaseModel):
    kafka: KafkaConfig = KafkaConfig()
    postgres: PostgresConfig = PostgresConfig()
    service: ServiceConfig = ServiceConfig()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        # env overrides
        if dsn := os.getenv("POSTGRES_DSN"):
            data.setdefault("postgres", {})["dsn"] = dsn
        if servers := os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
            data.setdefault("kafka", {})["bootstrap_servers"] = servers
        return cls(**data)
