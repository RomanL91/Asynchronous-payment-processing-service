"""Списание через платёжный шлюз."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ChargeStatus(StrEnum):
    """Итог списания со стороны шлюза."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ChargeRequest:
    """Запрос на списание.

    :ivar idempotency_key: ключ идемпотентности шлюза (= payment_id).
    """

    idempotency_key: str
    amount: Decimal
    currency: str
    description: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ChargeOutcome:
    """Ответ шлюза.

    :ivar replayed: шлюз вернул ранее сохранённый результат (повтор).
    """

    charge_id: str
    status: ChargeStatus
    processed_at: datetime
    replayed: bool
