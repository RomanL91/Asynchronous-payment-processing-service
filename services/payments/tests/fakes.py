"""In-memory двойники портов для unit-тестов сценариев."""

import asyncio
import itertools
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from payments_service.application.outbox import OutboxMessage
from payments_service.application.ports import (
    Clock,
    IdGenerator,
    OutboxRepository,
    PaymentRepository,
    UnitOfWork,
    WebhookNotification,
    WebhookSender,
)
from payments_service.domain import IdempotencyKey, Payment


class FixedClock(Clock):
    """Часы, сдвигаемые вручную."""

    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        """Текущее «время» теста."""
        return self.current

    def advance(self, seconds: float) -> None:
        """Сдвигает время."""
        self.current += timedelta(seconds=seconds)


class SequentialIds(IdGenerator):
    """Предсказуемые UUID: 00000000-…-000000000001, …02 и т.д."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new_id(self) -> UUID:
        """Следующий UUID."""
        return UUID(int=next(self._counter))


class InMemoryStore:
    """Общее «хранилище» для всех UoW теста (как одна БД)."""

    def __init__(self) -> None:
        self.payments: dict[UUID, Payment] = {}
        self.outbox: dict[UUID, OutboxMessage] = {}
        self.published: set[UUID] = set()
        self.commits = 0
        self.key_locks: dict[IdempotencyKey, asyncio.Event] = {}
        """Эмуляция блокировки уникального индекса до фиксации транзакции."""


class _PaymentRepository(PaymentRepository):
    def __init__(self, pending: dict[UUID, Payment], store: InMemoryStore) -> None:
        self._pending, self._store = pending, store

    def _visible(self) -> dict[UUID, Payment]:
        return {**self._store.payments, **self._pending}

    async def add_if_absent(self, payment: Payment) -> bool:
        key = payment.idempotency_key
        if (lock := self._store.key_locks.get(key)) is not None:
            await lock.wait()  # как PostgreSQL: ждём фиксации конкурента на уникальном индексе
        if any(p.idempotency_key == key for p in self._visible().values()):
            return False
        self._store.key_locks[key] = asyncio.Event()
        self._pending[payment.id] = payment
        return True

    async def get_by_idempotency_key(self, key: IdempotencyKey) -> Payment | None:
        found = next((p for p in self._visible().values() if p.idempotency_key == key), None)
        return replace(found) if found else None

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        found = self._visible().get(payment_id)
        return replace(found) if found else None

    async def update(self, payment: Payment) -> None:
        self._pending[payment.id] = replace(payment)


class _OutboxRepository(OutboxRepository):
    def __init__(self, pending: dict[UUID, OutboxMessage], store: InMemoryStore) -> None:
        self._pending, self._store = pending, store

    async def add_many(self, messages: Sequence[OutboxMessage]) -> None:
        self._pending.update({m.id: m for m in messages})

    async def lock_pending_batch(self, limit: int) -> list[OutboxMessage]:
        pending = [m for m in self._store.outbox.values() if m.id not in self._store.published]
        return sorted(pending, key=lambda m: m.created_at)[:limit]

    async def mark_published(self, message_ids: Sequence[UUID], at: datetime) -> None:
        self._store.published.update(message_ids)

    async def register_failure(self, message_id: UUID, error: str) -> None:
        return None


class InMemoryUnitOfWork(UnitOfWork):
    """UoW, применяющий изменения в общее хранилище только при commit."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._payments: dict[UUID, Payment] = {}
        self._outbox: dict[UUID, OutboxMessage] = {}
        self.payments = _PaymentRepository(self._payments, store)
        self.outbox = _OutboxRepository(self._outbox, store)

    async def commit(self) -> None:
        await asyncio.sleep(0)  # точка переключения: даём конкурентам дойти до блокировки
        self._release_locks()
        self._store.payments.update(self._payments)
        self._store.outbox.update(self._outbox)
        self._store.commits += 1
        self._payments.clear()
        self._outbox.clear()

    async def rollback(self) -> None:
        self._release_locks()
        self._payments.clear()
        self._outbox.clear()

    def _release_locks(self) -> None:
        for payment in self._payments.values():
            lock = self._store.key_locks.get(payment.idempotency_key)
            if lock is not None and not lock.is_set():
                lock.set()


class RecordingWebhookSender(WebhookSender):
    """Запоминает уведомления; может падать заданной ошибкой."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[WebhookNotification] = []
        self.error = error

    async def send(self, notification: WebhookNotification) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append(notification)
