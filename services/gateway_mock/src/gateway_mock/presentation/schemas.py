"""Схемы API шлюза."""

from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field

from gateway_mock.domain import Charge, ChargeStatus


class ChargeRequestBody(BaseModel):
    """Тело ``POST /v1/charges``."""

    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str = ""


class ChargeResponseBody(BaseModel):
    """Результат списания."""

    charge_id: str
    status: ChargeStatus
    amount: Decimal
    currency: str
    processed_at: datetime

    @classmethod
    def from_charge(cls, charge: Charge) -> Self:
        """Строит ответ из записи шлюза."""
        return cls(
            charge_id=charge.charge_id,
            status=charge.status,
            amount=charge.amount,
            currency=charge.currency,
            processed_at=charge.processed_at,
        )
