"""Тесты процессора: сценарий, HTTP-шлюз и сквозной поток через in-memory брокер."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from faststream.rabbit import TestRabbitBroker

from broker_kit.contracts import PaymentCreatedV1, PaymentProcessedV1, ProcessingStatus
from broker_kit.settings import BrokerSettings
from processor_service.application import ProcessPaymentCommand, ProcessPaymentHandler
from processor_service.application.ports import (
    GatewayRejectedError,
    GatewayUnavailableError,
    PaymentGateway,
    ProcessingResultPublisher,
)
from processor_service.bootstrap import ProcessorContainer
from processor_service.config import ProcessorSettings
from processor_service.domain import ChargeOutcome, ChargeRequest, ChargeStatus
from processor_service.infrastructure.gateway import HttpPaymentGateway
from processor_service.infrastructure.messaging import RabbitResultPublisher

NOW = datetime(2026, 10, 14, tzinfo=UTC)


class _Gateway(PaymentGateway):
    """Шлюз с фиксированным ответом."""

    def __init__(self, status: ChargeStatus = ChargeStatus.FAILED) -> None:
        self.requests: list[ChargeRequest] = []
        self._status = status

    async def charge(self, request: ChargeRequest) -> ChargeOutcome:
        self.requests.append(request)
        return ChargeOutcome(charge_id="ch_1", status=self._status, processed_at=NOW, replayed=False)


class _Publisher(ProcessingResultPublisher):
    """Публикатор, запоминающий события."""

    def __init__(self) -> None:
        self.events: list[PaymentProcessedV1] = []

    async def publish(self, event: PaymentProcessedV1) -> None:
        self.events.append(event)


async def test_failed_charge_is_published_as_business_result() -> None:
    """Отказ шлюза — обычный результат failed; ключ шлюза = payment_id."""
    gateway, publisher = _Gateway(ChargeStatus.FAILED), _Publisher()
    payment_id = uuid4()
    await ProcessPaymentHandler(gateway, publisher).handle(
        ProcessPaymentCommand(payment_id=payment_id, amount=Decimal("5.00"), currency="EUR", description="")
    )
    assert gateway.requests[0].idempotency_key == str(payment_id)
    assert publisher.events[0].status is ProcessingStatus.FAILED
    assert publisher.events[0].payment_id == payment_id


def _gateway(respond) -> HttpPaymentGateway:
    return HttpPaymentGateway(httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="http://gw"))


def _request() -> ChargeRequest:
    return ChargeRequest(idempotency_key="k", amount=Decimal("1.00"), currency="RUB", description="")


async def test_http_gateway_parses_replay() -> None:
    """200 → результат; заголовок повтора распознаётся."""
    body = {"charge_id": "ch_9", "status": "succeeded", "processed_at": NOW.isoformat(), "amount": "1.00"}
    outcome = await _gateway(lambda _: httpx.Response(200, json=body, headers={"Idempotent-Replayed": "true"})).charge(
        _request()
    )
    assert outcome.status is ChargeStatus.SUCCEEDED and outcome.replayed


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (503, GatewayUnavailableError),
        (429, GatewayUnavailableError),
        (422, GatewayRejectedError),
        (400, GatewayRejectedError),
    ],
)
async def test_http_gateway_classifies_errors(code: int, error: type[Exception]) -> None:
    """5xx/429 — временно; прочие 4xx — отклонено."""
    with pytest.raises(error):
        await _gateway(lambda _: httpx.Response(code)).charge(_request())


async def test_http_gateway_timeout_is_temporary() -> None:
    """Таймаут — временная ошибка."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(GatewayUnavailableError):
        await _gateway(timeout).charge(_request())


async def test_end_to_end_through_in_memory_broker() -> None:
    """payments.new → сценарий → payments.processed через FastStream TestRabbitBroker."""
    container = ProcessorContainer(ProcessorSettings(), BrokerSettings())
    topology = container.topology
    # Подменяем только шлюз: публикатор результата — настоящий RabbitResultPublisher
    container.__dict__["process_payment"] = ProcessPaymentHandler(
        _Gateway(ChargeStatus.SUCCEEDED),
        RabbitResultPublisher(container.broker, topology.processed_payments),
    )
    container.new_payments_subscription.register()
    received: list[dict] = []

    @container.broker.subscriber(topology.processed_payments.main_queue(), topology.processed_payments.exchange())
    async def capture(body: dict) -> None:
        received.append(body)

    payment_id = uuid4()
    created = PaymentCreatedV1(
        payment_id=payment_id, amount=Decimal("10.00"), currency="RUB", description="", created_at=NOW
    )
    async with TestRabbitBroker(container.broker) as broker:
        await broker.publish(
            json.loads(created.to_json_bytes()),
            exchange=topology.new_payments.exchange(),
            routing_key=topology.new_payments.routing_key,
        )

    expected = PaymentProcessedV1(
        payment_id=payment_id, status=ProcessingStatus.SUCCEEDED, gateway_charge_id="ch_1", processed_at=NOW
    )
    assert received == [json.loads(expected.to_json_bytes())]


async def test_gateway_client_is_traced(spans: InMemorySpanExporter) -> None:
    """Вызов шлюза даёт CLIENT-спан (закрытый порт: соединение отклоняется сразу)."""
    container = ProcessorContainer(ProcessorSettings(gateway_url="http://127.0.0.1:9"), BrokerSettings())
    with pytest.raises(httpx.ConnectError):
        await container.http_client.post("/v1/charges")
    await container.http_client.aclose()

    assert [s.kind for s in spans.get_finished_spans()] == [SpanKind.CLIENT]
