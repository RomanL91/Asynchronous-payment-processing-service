"""Доменные события платежа.

Доменное событие — внутренний факт предметной области. В интеграционное
событие (контракт брокера) его превращает прикладной слой, поэтому домен
не зависит от формата сообщений.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from payments_service.domain.value_objects import Money


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Базовое доменное событие.

    :ivar occurred_at: момент возникновения факта.
    """

    occurred_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentRegistered(DomainEvent):
    """Платёж принят к обработке."""

    payment_id: UUID
    money: Money
    description: str
