"""Общие тестовые двойники для broker_kit."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from broker_kit.reliability import ExponentialBackoff
from broker_kit.topology import PaymentsTopology, WorkQueueTopology


@dataclass
class FakeMessage:
    """Подделка входящего сообщения, фиксирующая исход доставки."""

    body: bytes = b"{}"
    headers: Mapping[str, Any] = field(default_factory=dict)
    message_id: str | None = "msg-1"
    content_type: str | None = "application/json"
    outcome: str | None = None

    async def ack(self) -> None:
        """Фиксирует ack."""
        self.outcome = "ack"

    async def nack(self, requeue: bool = True) -> None:
        """Фиксирует nack."""
        self.outcome = f"nack(requeue={requeue})"

    async def reject(self, requeue: bool = False) -> None:
        """Фиксирует reject."""
        self.outcome = f"reject(requeue={requeue})"


class RecordingRetryPublisher:
    """Подделка публикатора ретраев, запоминающая вызовы."""

    def __init__(self, fail: bool = False) -> None:
        """:param fail: имитировать сбой публикации."""
        self.calls: list[tuple[str, int]] = []
        self._fail = fail

    async def publish(self, message, queue, attempt, error) -> None:
        """Запоминает очередь и номер попытки."""
        if self._fail:
            raise ConnectionError("брокер недоступен")
        self.calls.append((queue.name, attempt.number))


@pytest.fixture
def topology() -> WorkQueueTopology:
    """Очередь новых платежей с тремя попытками."""
    return PaymentsTopology(ExponentialBackoff(1000, 2, 3)).new_payments


@pytest.fixture(scope="session")
def _span_exporter() -> InMemorySpanExporter:
    """Глобальный провайдер с in-memory экспортёром (ставится один раз на сессию)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(_span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    """Экспортёр, очищенный перед тестом."""
    _span_exporter.clear()
    return _span_exporter
