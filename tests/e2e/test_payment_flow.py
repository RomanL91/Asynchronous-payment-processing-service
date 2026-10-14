"""Сквозной сценарий варианта B в одном процессе.

Реальные компоненты: PostgreSQL, Unit of Work, outbox relay, обе подписки
с политикой надёжности, процессор, эмулятор шлюза (через ASGI-транспорт)
и webhook-клиент. Подменены только транспорты: RabbitMQ — на
``TestRabbitBroker`` FastStream (in-memory, синхронная маршрутизация),
HTTP — на ASGI/Mock-транспорты httpx.

Запуск: ``TEST_DATABASE_URL=postgresql+asyncpg://… pytest tests/e2e``.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pytest
from faststream.rabbit import TestRabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy import text, update

from broker_kit.factory import RabbitBrokerFactory
from broker_kit.observability import TraceTags
from broker_kit.settings import BrokerSettings
from gateway_mock.application import ChargeService, KeyedLock
from gateway_mock.domain import ChargeStatus, LatencyStrategy, OutcomeStrategy, ProbabilisticFaultInjector
from gateway_mock.infrastructure import InMemoryChargeStore
from gateway_mock.presentation.api import GatewayApiFactory
from payments_service.application.commands import RegisterPaymentCommand
from payments_service.bootstrap import PaymentsContainer
from payments_service.config import PaymentsSettings
from payments_service.domain import Currency
from payments_service.infrastructure.db.models import Base, OutboxModel, PaymentModel
from processor_service.bootstrap import ProcessorContainer
from processor_service.config import ProcessorSettings

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL не задан")


class _CountingOutcome(OutcomeStrategy):
    """Всегда успех; считает реальные списания шлюза."""

    def __init__(self) -> None:
        self.charges = 0

    def decide(self) -> ChargeStatus:
        self.charges += 1
        return ChargeStatus.SUCCEEDED


class _NoLatency(LatencyStrategy):
    async def wait(self) -> None:
        await asyncio.sleep(0)


@dataclass
class _System:
    """Собранная система и наблюдаемые точки."""

    payments: PaymentsContainer
    processor: ProcessorContainer
    outcome: _CountingOutcome
    webhooks: list[httpx.Request]
    webhook_status: list[int]
    retried: list[dict]


@pytest.fixture
async def system() -> AsyncIterator[_System]:
    """Оба сервиса на одном in-memory брокере и реальной БД."""
    broker = RabbitBrokerFactory(BrokerSettings()).create()
    broker_settings = BrokerSettings()

    payments = PaymentsContainer(PaymentsSettings(database_url=DATABASE_URL), broker_settings)
    processor = ProcessorContainer(ProcessorSettings(), broker_settings)
    payments.__dict__["broker"] = processor.__dict__["broker"] = broker

    outcome = _CountingOutcome()
    gateway_app = GatewayApiFactory(
        service=ChargeService(InMemoryChargeStore(), KeyedLock(), outcome, _NoLatency(), ProbabilisticFaultInjector(0))
    ).create()
    processor.__dict__["http_client"] = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app), base_url="http://gateway"
    )

    webhooks: list[httpx.Request] = []
    webhook_status = [200]

    def receive_webhook(request: httpx.Request) -> httpx.Response:
        webhooks.append(request)
        return httpx.Response(webhook_status[0])

    payments.__dict__["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(receive_webhook))

    async with payments.database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    processor.new_payments_subscription.register()
    payments.processed_payments_subscription.register()

    # In-memory брокер не эмулирует TTL, поэтому просто ловим копии в retry-очереди
    retried: list[dict] = []

    @broker.subscriber(payments.topology.processed_payments.retry_queue_after(1))
    async def capture_retry(body: dict, message: RabbitMessage) -> None:
        retried.append({"payment_id": body["payment_id"], "attempt": message.headers["x-attempt"]})

    async with TestRabbitBroker(broker):
        yield _System(payments, processor, outcome, webhooks, webhook_status, retried)

    async with payments.database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE payments, outbox"))
    await payments.aclose()
    await processor.aclose()


def _command(key: str) -> RegisterPaymentCommand:
    return RegisterPaymentCommand(
        idempotency_key=key,
        amount=Decimal("250.00"),
        currency=Currency.EUR,
        description="e2e",
        metadata={"source": "e2e"},
        webhook_url="https://shop.example/hook",
    )


async def _payment_row(system: _System, payment_id) -> PaymentModel:
    async with system.payments.database.session() as session:
        return await session.get(PaymentModel, payment_id)


async def test_full_flow_with_duplicate_delivery(system: _System) -> None:
    """API-команда → outbox → relay → processor → шлюз → результат → БД → webhook.

    Затем имитируем падение relay до отметки published_at: событие
    публикуется повторно. Шлюз не списывает второй раз, владелец платежа
    распознаёт дубль, второй webhook не отправляется.
    """
    acceptance = await system.payments.register_payment.handle(_command("e2e-1"))

    published = await system.payments.outbox_relay.relay_once()

    row = await _payment_row(system, acceptance.payment_id)
    assert published == 1
    assert row.status == "succeeded"
    assert row.webhook_delivered_at is not None
    assert system.outcome.charges == 1
    assert len(system.webhooks) == 1
    assert system.webhooks[0].headers["Idempotency-Key"] == str(acceptance.payment_id)

    # «Relay упал после confirm, но до COMMIT»: сообщение снова неопубликовано
    async with system.payments.database.engine.begin() as connection:
        await connection.execute(update(OutboxModel).values(published_at=None))
    assert await system.payments.outbox_relay.relay_once() == 1

    assert system.outcome.charges == 1, "шлюз не должен списывать повторно"
    assert len(system.webhooks) == 1, "дубль результата не должен слать второй webhook"


async def test_webhook_failure_goes_to_retry_queue(system: _System) -> None:
    """Webhook 503: статус зафиксирован, сообщение ушло в payments.processed.retry.1."""
    system.webhook_status[0] = 503
    acceptance = await system.payments.register_payment.handle(_command("e2e-2"))
    await system.payments.outbox_relay.relay_once()

    row = await _payment_row(system, acceptance.payment_id)
    assert row.status == "succeeded"
    assert row.webhook_delivered_at is None
    assert system.retried == [{"payment_id": str(acceptance.payment_id), "attempt": 2}]


async def test_async_flow_is_one_trace_tagged_with_payment(system: _System, spans: InMemorySpanExporter) -> None:
    """relay → processor → consumer: один трейс; обе обработки несут payment.id."""
    acceptance = await system.payments.register_payment.handle(_command("e2e-trace"))
    spans.clear()

    await system.payments.outbox_relay.relay_once()

    # Спаны брокера; gateway-mock здесь в том же процессе, но в системе он внешний и не трассируется
    messaging = [s for s in spans.get_finished_spans() if s.kind in (SpanKind.PRODUCER, SpanKind.CONSUMER)]
    consumers = [s for s in messaging if s.kind is SpanKind.CONSUMER]
    assert len({s.context.trace_id for s in messaging}) == 1
    assert len(consumers) == 2, "payments.new и payments.processed"
    assert {s.attributes.get(TraceTags.PAYMENT_ID) for s in consumers} == {str(acceptance.payment_id)}
