"""Настройки processor-service."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProcessorSettings(BaseSettings):
    """Параметры из окружения с префиксом ``PROCESSOR_``."""

    model_config = SettingsConfigDict(env_prefix="PROCESSOR_", extra="ignore")

    gateway_url: str = Field(default="http://localhost:8001", description="Базовый URL платёжного шлюза.")
    gateway_timeout_s: float = Field(
        default=15.0,
        gt=0,
        description="Таймаут запроса к шлюзу; должен превышать его максимальную задержку (5 с).",
    )
    log_level: str = Field(default="INFO")
