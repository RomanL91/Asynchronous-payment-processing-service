"""Единая настройка логирования и трассировки сервисов."""

import logging
import os
import sys
from typing import Final
from uuid import UUID

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class LoggingConfigurator:
    """Настраивает корневой логгер процесса.

    Формат одинаков во всех контейнерах, что упрощает чтение
    ``docker compose logs`` по нескольким сервисам сразу.
    """

    _FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

    def __init__(self, service_name: str, level: int | str = logging.INFO) -> None:
        """Сохраняет параметры.

        :param service_name: имя сервиса, выводится при старте.
        :param level: уровень логирования.
        """
        self._service_name = service_name
        self._level = level

    def configure(self) -> logging.Logger:
        """Применяет конфигурацию и возвращает логгер сервиса.

        :return: логгер с именем сервиса.
        """
        logging.basicConfig(level=self._level, format=self._FORMAT, stream=sys.stdout, force=True)
        logger = logging.getLogger(self._service_name)
        logger.info("Логирование настроено для сервиса %s", self._service_name)
        return logger


class TracingConfigurator:
    """Включает экспорт трейсов по OTLP, если задан ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    Без переменной глобальный провайдер не трогается: спаны создаются
    no-op-трейсером и никуда не уходят. Последнюю пачку при выходе
    процесса сбрасывает сам SDK (``atexit``).
    """

    ENDPOINT_VARIABLE: Final[str] = "OTEL_EXPORTER_OTLP_ENDPOINT"

    def __init__(self, service_name: str) -> None:
        """:param service_name: имя сервиса в Jaeger."""
        self._service_name = service_name

    def build(self) -> TracerProvider | None:
        """Собирает провайдер.

        :return: провайдер с OTLP-экспортом или ``None``, если трассировка выключена.
        """
        if not os.getenv(self.ENDPOINT_VARIABLE):
            return None
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: self._service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        return provider

    def configure(self) -> None:
        """Устанавливает провайдер глобально, если трассировка включена."""
        provider = self.build()
        if provider is not None:
            trace.set_tracer_provider(provider)


class TraceTags:
    """Бизнес-атрибуты спанов, по которым ищут в Jaeger."""

    PAYMENT_ID: Final[str] = "payment.id"

    @classmethod
    def tag_payment(cls, payment_id: UUID) -> None:
        """Помечает текущий спан идентификатором платежа.

        :param payment_id: идентификатор платежа.
        """
        trace.get_current_span().set_attribute(cls.PAYMENT_ID, str(payment_id))
