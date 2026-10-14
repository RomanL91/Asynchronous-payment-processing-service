"""Агрегат «Платёж»."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from payments_service.domain.events import DomainEvent, PaymentRegistered
from payments_service.domain.states import OutcomeResolution, PaymentStateRegistry
from payments_service.domain.value_objects import IdempotencyKey, Money, PaymentStatus, RequestFingerprint


@dataclass(slots=True, kw_only=True)
class Payment:
    """Корень агрегата платежа.

    Изменение статуса делегируется объекту состояния (паттерн State).
    Доменные события накапливаются внутри агрегата и забираются
    прикладным слоем для записи в outbox в той же транзакции.
    """

    id: UUID
    idempotency_key: IdempotencyKey
    fingerprint: RequestFingerprint
    money: Money
    description: str
    metadata: dict[str, Any]
    webhook_url: str
    status: PaymentStatus
    created_at: datetime
    processed_at: datetime | None = None
    webhook_delivered_at: datetime | None = None
    _events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def register(
        cls,
        *,
        payment_id: UUID,
        idempotency_key: IdempotencyKey,
        fingerprint: RequestFingerprint,
        money: Money,
        description: str,
        metadata: dict[str, Any],
        webhook_url: str,
        now: datetime,
    ) -> Self:
        """Создаёт новый платёж в статусе ``pending``.

        :return: платёж с доменным событием ``PaymentRegistered``.
        """
        payment = cls(
            id=payment_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            money=money,
            description=description,
            metadata=dict(metadata),
            webhook_url=webhook_url,
            status=PaymentStatus.PENDING,
            created_at=now,
        )
        payment._events.append(
            PaymentRegistered(occurred_at=now, payment_id=payment_id, money=money, description=description)
        )
        return payment

    def apply_outcome(self, outcome: PaymentStatus, processed_at: datetime) -> OutcomeResolution:
        """Применяет результат обработки шлюзом.

        :param outcome: ``succeeded`` или ``failed``.
        :param processed_at: момент обработки.
        :return: применён результат или это повтор.
        """
        return PaymentStateRegistry.for_status(self.status).apply_outcome(self, outcome, processed_at)

    @property
    def awaits_webhook(self) -> bool:
        """Нужно ли ещё уведомить клиента о результате."""
        return self.status.is_final and self.webhook_delivered_at is None

    def mark_webhook_delivered(self, at: datetime) -> bool:
        """Фиксирует успешную доставку webhook (идемпотентно).

        :param at: момент доставки.
        :return: ``True``, если отметка поставлена впервые.
        """
        if not self.awaits_webhook:
            return False
        self.webhook_delivered_at = at
        return True

    def pull_events(self) -> list[DomainEvent]:
        """Забирает накопленные доменные события, очищая буфер."""
        events, self._events = self._events, []
        return events
