"""Модели чтения (read side CQRS)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from payments_service.domain import Currency, Payment, PaymentStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentDetails:
    """Плоская проекция платежа для ответа API."""

    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None
    webhook_delivered_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentAcceptance:
    """Результат команды регистрации платежа.

    :ivar replayed: ``True`` — ответ на повтор запроса с тем же ключом,
        новый платёж не создавался.
    """

    payment_id: UUID
    status: PaymentStatus
    created_at: datetime
    replayed: bool

    @classmethod
    def of(cls, payment: Payment, *, replayed: bool) -> "PaymentAcceptance":
        """Строит результат из агрегата."""
        return cls(payment_id=payment.id, status=payment.status, created_at=payment.created_at, replayed=replayed)
