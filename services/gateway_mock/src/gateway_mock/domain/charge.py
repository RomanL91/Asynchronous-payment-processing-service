"""Списание (charge)."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ChargeStatus(StrEnum):
    """Итог списания."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdempotencyMismatchError(Exception):
    """Ключ уже использован для списания с другими параметрами."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ChargeRequest:
    """Входящий запрос на списание."""

    idempotency_key: str
    amount: Decimal
    currency: str
    description: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Charge:
    """Проведённое списание — неизменяемая запись шлюза."""

    charge_id: str
    idempotency_key: str
    amount: Decimal
    currency: str
    status: ChargeStatus
    processed_at: datetime

    def ensure_matches(self, request: ChargeRequest) -> None:
        """Повтор допустим только с теми же суммой и валютой.

        :raises IdempotencyMismatchError: параметры отличаются.
        """
        if (self.amount, self.currency) != (request.amount, request.currency):
            raise IdempotencyMismatchError(
                f"Ключ {self.idempotency_key} уже использован для {self.amount} {self.currency}"
            )
