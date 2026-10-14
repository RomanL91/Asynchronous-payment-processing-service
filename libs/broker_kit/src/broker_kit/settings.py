"""Настройки подключения к RabbitMQ и политики повторных попыток."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerSettings(BaseSettings):
    """Параметры брокера, общие для всех сервисов.

    Читаются из переменных окружения с префиксом ``RABBITMQ_``.
    Параметры ретраев влияют на топологию (TTL retry-очередей), поэтому
    во всех сервисах должны быть одинаковыми — в docker-compose они
    передаются из общего блока окружения.
    """

    model_config = SettingsConfigDict(env_prefix="RABBITMQ_", extra="ignore")

    url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        description="AMQP URL подключения к RabbitMQ.",
    )
    prefetch_count: int = Field(
        default=16,
        ge=1,
        description=(
            "Сколько неподтверждённых сообщений канал получает одновременно. "
            "Каждое сообщение обрабатывается отдельной задачей event loop, "
            "поэтому это же — верхняя граница конкурентности потребителя."
        ),
    )
    retry_max_attempts: int = Field(
        default=3,
        ge=1,
        description="Общее число попыток обработки, включая первую.",
    )
    retry_base_delay_ms: int = Field(
        default=1000,
        ge=1,
        description="Задержка перед первой повторной попыткой.",
    )
    retry_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="Множитель экспоненциальной задержки.",
    )
