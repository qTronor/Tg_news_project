from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/tg_news_auth"
    analytics_database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/telegram_news"

    jwt_secret_key: str = "CHANGE-ME-in-production-use-KMS"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    cors_origins: list[str] = ["http://localhost:3000"]

    rate_limit_per_minute: int = 30

    admin_bootstrap_email: str | None = None
    admin_bootstrap_password: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@tgnews.local"
    smtp_tls: bool = True

    frontend_url: str = "http://localhost:3000"

    model_config = {"env_prefix": "AUTH_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
