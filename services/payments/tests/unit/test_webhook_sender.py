"""Тесты классификации ответов получателя webhook."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from broker_kit.settings import BrokerSettings
from payments_service.application.ports import (
    WebhookNotification,
    WebhookPermanentlyRejectedError,
    WebhookTemporarilyUnavailableError,
)
from payments_service.bootstrap import PaymentsContainer
from payments_service.config import PaymentsSettings
from payments_service.infrastructure.webhook import HttpxWebhookSender, WebhookResponsePolicy


def _notification() -> WebhookNotification:
    return WebhookNotification(
        url="https://shop.example/hook",
        payment_id=uuid4(),
        status="succeeded",
        amount="10.00",
        currency="RUB",
        metadata={},
        processed_at=datetime(2026, 10, 14, tzinfo=UTC),
    )


def _sender(handler: httpx.MockTransport) -> HttpxWebhookSender:
    return HttpxWebhookSender(httpx.AsyncClient(transport=handler), WebhookResponsePolicy())


@pytest.mark.parametrize("code", [200, 201, 204])
async def test_success_codes(code: int) -> None:
    """2xx — доставлено; заголовок Idempotency-Key = payment_id."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(code)

    notification = _notification()
    await _sender(httpx.MockTransport(respond)).send(notification)
    assert seen[0].headers["Idempotency-Key"] == str(notification.payment_id)


@pytest.mark.parametrize("code", [408, 425, 429, 500, 502, 503])
async def test_temporary_codes(code: int) -> None:
    """408/425/429/5xx — временная ошибка."""
    with pytest.raises(WebhookTemporarilyUnavailableError):
        await _sender(httpx.MockTransport(lambda _: httpx.Response(code))).send(_notification())


@pytest.mark.parametrize("code", [301, 400, 401, 404, 410, 422])
async def test_permanent_codes(code: int) -> None:
    """Прочие коды — получатель отверг уведомление."""
    with pytest.raises(WebhookPermanentlyRejectedError):
        await _sender(httpx.MockTransport(lambda _: httpx.Response(code))).send(_notification())


async def test_network_error_is_temporary() -> None:
    """Сетевая ошибка — временная."""

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(WebhookTemporarilyUnavailableError):
        await _sender(httpx.MockTransport(fail)).send(_notification())


async def test_container_webhook_client_is_traced(spans: InMemorySpanExporter) -> None:
    """Отправка webhook даёт CLIENT-спан (закрытый порт: соединение отклоняется сразу)."""
    container = PaymentsContainer(PaymentsSettings(), BrokerSettings())
    with pytest.raises(httpx.ConnectError):
        await container.http_client.post("http://127.0.0.1:9/hook")
    await container.http_client.aclose()

    assert [s.kind for s in spans.get_finished_spans()] == [SpanKind.CLIENT]
