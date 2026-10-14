"""Идемпотентное списание."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from gateway_mock.application.keyed_lock import KeyedLock
from gateway_mock.application.ports import ChargeStore
from gateway_mock.domain import Charge, ChargeRequest, FaultInjector, LatencyStrategy, OutcomeStrategy


@dataclass(frozen=True, slots=True)
class ChargeResult:
    """Списание и признак того, что это повтор."""

    charge: Charge
    replayed: bool


class ChargeService:
    """Проводит списание ровно один раз на ключ идемпотентности.

    Алгоритм под блокировкой ключа (single-flight):

    1. есть сохранённое списание → сверить параметры и вернуть его;
    2. нет → «обработать» (задержка + исход), сохранить, вернуть.

    Блокировка по ключу, а не глобальная: разные платежи
    обрабатываются конкурентно, одинаковые — строго последовательно.
    """

    def __init__(
        self,
        store: ChargeStore,
        locks: KeyedLock,
        outcome: OutcomeStrategy,
        latency: LatencyStrategy,
        faults: FaultInjector,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._store = store
        self._locks = locks
        self._outcome = outcome
        self._latency = latency
        self._faults = faults
        self._clock = clock or (lambda: datetime.now(UTC))

    async def charge(self, request: ChargeRequest) -> ChargeResult:
        """Проводит или воспроизводит списание.

        :raises GatewayOverloadedError: внедрённый временный сбой.
        :raises IdempotencyMismatchError: ключ использован с другими параметрами.
        """
        self._faults.maybe_fail()
        async with self._locks.hold(request.idempotency_key):
            existing = await self._store.get(request.idempotency_key)
            if existing is not None:
                existing.ensure_matches(request)
                return ChargeResult(existing, replayed=True)
            charge = await self._process(request)
            await self._store.save(charge)
            return ChargeResult(charge, replayed=False)

    async def _process(self, request: ChargeRequest) -> Charge:
        """Эмулирует обработку нового списания."""
        await self._latency.wait()
        return Charge(
            charge_id=f"ch_{uuid.uuid4().hex}",
            idempotency_key=request.idempotency_key,
            amount=request.amount,
            currency=request.currency,
            status=self._outcome.decide(),
            processed_at=self._clock(),
        )
