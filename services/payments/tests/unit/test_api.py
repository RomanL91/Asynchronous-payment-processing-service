"""Тесты HTTP API на in-memory сценариях."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import SecretStr

from broker_kit.observability import TraceTags
from payments_service.application.commands import RegisterPaymentHandler
from payments_service.application.queries import GetPaymentHandler
from payments_service.application.read_models import PaymentDetails
from payments_service.config import PaymentsSettings
from payments_service.presentation.api.app import ApiApplicationFactory
from tests.fakes import InMemoryStore

API_KEY = "test-key"
BODY = {
    "amount": "100.50",
    "currency": "USD",
    "description": "Подписка",
    "metadata": {"plan": "pro"},
    "webhook_url": "https://shop.example/hook",
}


class _StoreReader:
    """Читатель проекций поверх in-memory хранилища."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get_details(self, payment_id):
        payment = self._store.payments.get(payment_id)
        if payment is None:
            return None
        return PaymentDetails(
            id=payment.id,
            amount=payment.money.amount,
            currency=payment.money.currency,
            description=payment.description,
            metadata=payment.metadata,
            status=payment.status,
            idempotency_key=payment.idempotency_key.value,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
            webhook_delivered_at=payment.webhook_delivered_at,
        )


class _Container:
    """Минимальный контейнер для API."""

    def __init__(self, register: RegisterPaymentHandler, store: InMemoryStore) -> None:
        self.register_payment = register
        self.get_payment = GetPaymentHandler(_StoreReader(store))

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client(register_handler: RegisterPaymentHandler, store: InMemoryStore) -> Iterator[TestClient]:
    """Клиент приложения с подменённым контейнером."""
    settings = PaymentsSettings(api_key=SecretStr(API_KEY))
    app = ApiApplicationFactory(settings, container=_Container(register_handler, store)).create()  # type: ignore[arg-type]
    with TestClient(app) as test_client:
        yield test_client


def _post(client: TestClient, key: str = "key-1", body: dict | None = None, api_key: str = API_KEY):
    return client.post(
        "/api/v1/payments",
        json=body or BODY,
        headers={"X-API-Key": api_key, "Idempotency-Key": key},
    )


def test_create_returns_202_and_get_returns_details(client: TestClient) -> None:
    """POST → 202 pending; GET → детали платежа."""
    created = _post(client)
    assert created.status_code == 202
    assert created.headers["Idempotent-Replayed"] == "false"
    payment_id = created.json()["payment_id"]
    assert created.json()["status"] == "pending"

    details = client.get(f"/api/v1/payments/{payment_id}", headers={"X-API-Key": API_KEY})
    assert details.status_code == 200
    assert details.json()["amount"] == "100.50"
    assert details.json()["metadata"] == {"plan": "pro"}


def test_replay_and_conflict(client: TestClient) -> None:
    """Повтор → тот же id с флагом; другое тело → 409."""
    first = _post(client).json()
    replay = _post(client)
    assert replay.status_code == 202
    assert replay.json()["payment_id"] == first["payment_id"]
    assert replay.headers["Idempotent-Replayed"] == "true"

    conflict = _post(client, body={**BODY, "amount": "1.00"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_key_conflict"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [({}, 401), ({"X-API-Key": "wrong"}, 401), ({"X-API-Key": API_KEY}, 422)],
)
def test_auth_and_required_idempotency_key(client: TestClient, headers: dict, expected: int) -> None:
    """Без ключа/с неверным ключом — 401; без Idempotency-Key — 422."""
    assert client.post("/api/v1/payments", json=BODY, headers=headers).status_code == expected


def test_get_requires_key_and_returns_404(client: TestClient) -> None:
    """GET защищён ключом; неизвестный платёж — 404."""
    unknown = "00000000-0000-7000-8000-000000000000"
    assert client.get(f"/api/v1/payments/{unknown}").status_code == 401
    assert client.get(f"/api/v1/payments/{unknown}", headers={"X-API-Key": API_KEY}).status_code == 404


@pytest.mark.parametrize(
    "patch",
    [{"amount": "0"}, {"amount": "1.001"}, {"currency": "GBP"}, {"webhook_url": "not-a-url"}, {"extra": 1}],
)
def test_validation(client: TestClient, patch: dict) -> None:
    """Некорректное тело — 422."""
    assert _post(client, body={**BODY, **patch}).status_code == 422


def test_create_tags_request_trace_with_payment_id(client: TestClient, spans: InMemorySpanExporter) -> None:
    """Трейс POST /api/v1/payments несёт payment.id — по нему ищут в Jaeger."""
    payment_id = _post(client).json()["payment_id"]

    finished = spans.get_finished_spans()
    (server,) = [s for s in finished if s.kind is SpanKind.SERVER]
    tagged = [s for s in finished if s.attributes.get(TraceTags.PAYMENT_ID) == payment_id]
    assert [s.context.trace_id for s in tagged] == [server.context.trace_id]


def test_health_is_public(client: TestClient) -> None:
    """Проверка живости для docker healthcheck — без API-ключа."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
