"""Настройки приложения. Всё берётся из переменных окружения (см. infra/.env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_", env_file=None, extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Ключ доступен только API; repr настроек скрывает его значение.
    openrouter_api_key: SecretStr = SecretStr("")
    assistant_model: str = "deepseek/deepseek-v4.1-flash-1017"
    assistant_daily_turns: int = Field(default=100, ge=1, le=10000)
    assistant_timeout_seconds: int = Field(default=40, ge=5, le=45)

    # Драйвер psycopg 3; формат: postgresql+psycopg://user:pass@host:5432/db
    database_url: str = "postgresql+psycopg://cashcast:cashcast@localhost:5432/cashcast"

    # Сессия пользователя. Secure-cookie обязательна за HTTPS; локально через http выключаем.
    session_cookie_name: str = "cc_session"
    csrf_cookie_name: str = "cc_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_ttl_hours: int = 12
    cookie_secure: bool = False

    # Выписка малого бизнеса за 2 года — сотни килобайт; 10 МБ с большим запасом.
    max_upload_bytes: int = 10 * 1024 * 1024

    forecast_default_horizon_days: int = 30
    forecast_max_horizon_days: int = 180
    forecast_default_seed: int = 42

    # Аренда задания: если worker умер, через это время задание заберёт другой.
    job_lease_seconds: int = 300
    job_max_attempts: int = 3
    worker_poll_seconds: float = Field(default=1.0, gt=0)

    # Сид демо-данных при старте контейнера миграций (только для dev/демо).
    seed_demo: bool = False
    demo_email: str = "demo@example.com"
    demo_password: str = "demo-password"


@lru_cache
def get_settings() -> Settings:
    return Settings()
