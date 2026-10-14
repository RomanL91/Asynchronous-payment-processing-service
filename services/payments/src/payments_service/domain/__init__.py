"""Доменный слой: платёж и его правила.

Не зависит ни от фреймворков, ни от БД, ни от брокера. Здесь живут
инварианты: сумма положительна и имеет не более двух знаков, статус
меняется только из ``pending`` и только один раз.
"""

from payments_service.domain.events import DomainEvent, PaymentRegistered
from payments_service.domain.exceptions import DomainError, InvalidIdempotencyKeyError, InvalidMoneyError
from payments_service.domain.payment import Payment
from payments_service.domain.states import OutcomeResolution
from payments_service.domain.value_objects import (
    Currency,
    IdempotencyKey,
    Money,
    PaymentStatus,
    RequestFingerprint,
)

__all__ = [
    "Currency",
    "DomainError",
    "DomainEvent",
    "IdempotencyKey",
    "InvalidIdempotencyKeyError",
    "InvalidMoneyError",
    "Money",
    "OutcomeResolution",
    "Payment",
    "PaymentRegistered",
    "PaymentStatus",
    "RequestFingerprint",
]
