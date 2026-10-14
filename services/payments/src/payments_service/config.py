"""Настройки payments-service."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class PaymentsSettings(BaseSettings):
    """Параметры сервиса из переменных окружения с префиксом ``PAYMENTS_``.

    Настройки брокера живут отдельно — в ``broker_kit.settings.BrokerSettings``.
    """

    model_config = SettingsConfigDict(env_prefix="PAYMENTS_", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://payments:payments@localhost:5432/payments",
        description="DSN PostgreSQL с асинхронным драйвером asyncpg.",
    )
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=5, ge=0)

    api_key: SecretStr = Field(default=SecretStr("change-me"), description="Статический ключ X-API-Key.")

    outbox_batch_size: int = Field(default=100, ge=1, description="Размер пачки relay.")
    outbox_poll_interval_s: float = Field(default=0.5, gt=0, description="Пауза, когда outbox пуст.")

    webhook_timeout_s: float = Field(default=5.0, gt=0, description="Таймаут запроса webhook.")

    log_level: str = Field(default="INFO")
