"""Фикстуры сценарных тестов payments-service."""

from decimal import Decimal

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from payments_service.application.commands import (
    ApplyProcessingResultHandler,
    DeliverWebhookHandler,
    RegisterPaymentCommand,
    RegisterPaymentHandler,
)
from payments_service.application.commands.register_payment import IdempotentReplayGuard
from payments_service.application.fingerprint import RequestFingerprintCalculator
from payments_service.application.integration import OutboxMessageMapper
from payments_service.domain import Currency
from tests.fakes import FixedClock, InMemoryStore, InMemoryUnitOfWork, RecordingWebhookSender, SequentialIds


@pytest.fixture
def store() -> InMemoryStore:
    """Общее in-memory хранилище."""
    return InMemoryStore()


@pytest.fixture
def clock() -> FixedClock:
    """Управляемые часы."""
    return FixedClock()


@pytest.fixture
def webhook_sender() -> RecordingWebhookSender:
    """Отправитель webhook, запоминающий вызовы."""
    return RecordingWebhookSender()


@pytest.fixture
def register_handler(store: InMemoryStore, clock: FixedClock) -> RegisterPaymentHandler:
    """Команда регистрации на in-memory портах."""
    ids = SequentialIds()
    return RegisterPaymentHandler(
        uow_factory=lambda: InMemoryUnitOfWork(store),
        clock=clock,
        ids=ids,
        fingerprints=RequestFingerprintCalculator(),
        outbox_mapper=OutboxMessageMapper(ids),
        replay_guard=IdempotentReplayGuard(),
    )


@pytest.fixture
def apply_handler(
    store: InMemoryStore,
    clock: FixedClock,
    webhook_sender: RecordingWebhookSender,
) -> ApplyProcessingResultHandler:
    """Команда применения результата на in-memory портах."""
    delivery = DeliverWebhookHandler(lambda: InMemoryUnitOfWork(store), webhook_sender, clock)
    return ApplyProcessingResultHandler(lambda: InMemoryUnitOfWork(store), delivery)


def make_command(key: str = "order-1042", amount: str = "1500.00", **overrides: object) -> RegisterPaymentCommand:
    """Команда регистрации с разумными значениями по умолчанию."""
    params: dict[str, object] = {
        "idempotency_key": key,
        "amount": Decimal(amount),
        "currency": Currency.RUB,
        "description": "Оплата заказа",
        "metadata": {"order_id": 1042},
        "webhook_url": "https://shop.example/webhooks/payments",
    }
    params.update(overrides)
    return RegisterPaymentCommand(**params)  # type: ignore[arg-type]


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
