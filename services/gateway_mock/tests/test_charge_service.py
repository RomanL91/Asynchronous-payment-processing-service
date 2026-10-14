"""Идемпотентность и single-flight шлюза."""

import asyncio
from decimal import Decimal

import httpx
import pytest

from gateway_mock.application import ChargeService, KeyedLock
from gateway_mock.domain import (
    ChargeRequest,
    ChargeStatus,
    GatewayOverloadedError,
    IdempotencyMismatchError,
    LatencyStrategy,
    OutcomeStrategy,
    ProbabilisticFaultInjector,
)
from gateway_mock.infrastructure import InMemoryChargeStore
from gateway_mock.presentation.api import GatewayApiFactory


class _CountingOutcome(OutcomeStrategy):
    """Чередует исходы и считает «реальные» списания."""

    def __init__(self) -> None:
        self.calls = 0

    def decide(self) -> ChargeStatus:
        self.calls += 1
        return ChargeStatus.SUCCEEDED if self.calls % 2 else ChargeStatus.FAILED


class _Latency(LatencyStrategy):
    """Короткая, но реальная пауза — точка переключения event loop."""

    async def wait(self) -> None:
        await asyncio.sleep(0.01)


def _service(outcome: _CountingOutcome, failure_rate: float = 0.0) -> tuple[ChargeService, KeyedLock]:
    locks = KeyedLock()
    service = ChargeService(
        store=InMemoryChargeStore(),
        locks=locks,
        outcome=outcome,
        latency=_Latency(),
        faults=ProbabilisticFaultInjector(failure_rate),
    )
    return service, locks


def _request(key: str = "pay-1", amount: str = "10.00") -> ChargeRequest:
    return ChargeRequest(idempotency_key=key, amount=Decimal(amount), currency="RUB", description="")


async def test_repeat_returns_saved_result_without_new_charge() -> None:
    """Повтор с тем же ключом — тот же результат, исход не перебрасывается."""
    outcome = _CountingOutcome()
    service, _ = _service(outcome)
    first = await service.charge(_request())
    second = await service.charge(_request())

    assert outcome.calls == 1
    assert second.replayed and not first.replayed
    assert second.charge == first.charge


async def test_concurrent_same_key_is_single_flight() -> None:
    """50 одновременных запросов по одному ключу — одно списание, реестр блокировок пуст."""
    outcome = _CountingOutcome()
    service, locks = _service(outcome)
    results = await asyncio.gather(*(service.charge(_request()) for _ in range(50)))

    assert outcome.calls == 1
    assert len({r.charge.charge_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert len(locks) == 0


async def test_different_keys_run_concurrently() -> None:
    """Разные ключи не ждут друг друга: 20 списаний по 10 мс укладываются в ~10 мс."""
    service, _ = _service(_CountingOutcome())
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(*(service.charge(_request(f"k-{i}")) for i in range(20)))
    assert loop.time() - started < 0.15


async def test_mismatched_repeat_is_rejected() -> None:
    """Тот же ключ с другой суммой — ошибка."""
    service, _ = _service(_CountingOutcome())
    await service.charge(_request())
    with pytest.raises(IdempotencyMismatchError):
        await service.charge(_request(amount="99.00"))


async def test_fault_injection() -> None:
    """При 100% сбоев шлюз отвечает «перегружен» и ничего не сохраняет."""
    outcome = _CountingOutcome()
    service, _ = _service(outcome, failure_rate=1.0)
    with pytest.raises(GatewayOverloadedError):
        await service.charge(_request())
    assert outcome.calls == 0


async def test_http_contract() -> None:
    """HTTP: 200 + Idempotent-Replayed; 503 при сбое; 422 без ключа."""
    service, _ = _service(_CountingOutcome())
    app = GatewayApiFactory(service=service).create()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as client:
        body = {"amount": "10.00", "currency": "RUB"}
        first = await client.post("/v1/charges", json=body, headers={"Idempotency-Key": "p-1"})
        second = await client.post("/v1/charges", json=body, headers={"Idempotency-Key": "p-1"})
        missing_key = await client.post("/v1/charges", json=body)

    assert first.status_code == 200 and first.headers["Idempotent-Replayed"] == "false"
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["charge_id"] == first.json()["charge_id"]
    assert missing_key.status_code == 422

    overloaded_service, _ = _service(_CountingOutcome(), failure_rate=1.0)
    app = GatewayApiFactory(service=overloaded_service).create()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as client:
        response = await client.post("/v1/charges", json=body, headers={"Idempotency-Key": "p-2"})
    assert response.status_code == 503
