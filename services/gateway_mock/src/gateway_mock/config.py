"""Настройки эмулятора шлюза."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Параметры из окружения с префиксом ``GATEWAY_``."""

    model_config = SettingsConfigDict(env_prefix="GATEWAY_", extra="ignore")

    min_latency_s: float = Field(default=2.0, ge=0, description="Минимальная задержка обработки.")
    max_latency_s: float = Field(default=5.0, ge=0, description="Максимальная задержка обработки.")
    success_rate: float = Field(default=0.9, ge=0, le=1, description="Доля успешных списаний.")
    transient_failure_rate: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Доля ответов 503 до обработки — для демонстрации ретраев процессора.",
    )

    @model_validator(mode="after")
    def _check_latency_range(self) -> "GatewaySettings":
        """Нижняя граница задержки не больше верхней."""
        if self.min_latency_s > self.max_latency_s:
            raise ValueError("min_latency_s не может превышать max_latency_s")
        return self
