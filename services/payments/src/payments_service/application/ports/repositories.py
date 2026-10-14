"""Порты репозиториев."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from payments_service.application.outbox import OutboxMessage
from payments_service.domain import IdempotencyKey, Payment


class PaymentRepository(ABC):
    """Коллекция агрегатов «Платёж» (паттерн Repository)."""

    @abstractmethod
    async def add_if_absent(self, payment: Payment) -> bool:
        """Атомарно добавляет платёж, если его ключ идемпотентности свободен.

        :return: ``True`` — добавлен; ``False`` — ключ уже занят.
        """

    @abstractmethod
    async def get_by_idempotency_key(self, key: IdempotencyKey) -> Payment | None:
        """Ищет платёж по ключу идемпотентности."""

    @abstractmethod
    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        """Загружает платёж с блокировкой строки до конца транзакции."""

    @abstractmethod
    async def update(self, payment: Payment) -> None:
        """Сохраняет изменяемые поля платежа."""


class OutboxRepository(ABC):
    """Хранилище сообщений transactional outbox."""

    @abstractmethod
    async def add_many(self, messages: Sequence[OutboxMessage]) -> None:
        """Добавляет сообщения одной вставкой."""

    @abstractmethod
    async def lock_pending_batch(self, limit: int) -> list[OutboxMessage]:
        """Блокирует и возвращает пачку неопубликованных сообщений.

        Строки, уже заблокированные другим relay, пропускаются, поэтому
        несколько экземпляров relay работают параллельно без дублей.
        """

    @abstractmethod
    async def mark_published(self, message_ids: Sequence[UUID], at: datetime) -> None:
        """Отмечает сообщения опубликованными одним запросом."""

    @abstractmethod
    async def register_failure(self, message_id: UUID, error: str) -> None:
        """Увеличивает счётчик неудачных публикаций и сохраняет ошибку."""
