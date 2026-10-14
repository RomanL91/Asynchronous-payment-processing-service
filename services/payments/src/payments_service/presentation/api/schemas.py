"""Pydantic-схемы HTTP API."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from payments_service.application.read_models import PaymentAcceptance, PaymentDetails
from payments_service.domain import Currency, PaymentStatus


class CreatePaymentRequest(BaseModel):
    """Тело ``POST /api/v1/payments``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "amount": "1500.00",
                "currency": "RUB",
                "description": "Оплата заказа #1042",
                "metadata": {"order_id": 1042},
                "webhook_url": "http://webhook-receiver:8080/status/200",
            }
        },
    )

    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2, description="Сумма, не более 2 знаков.")
    currency: Currency
    description: str = Field(min_length=1, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict, description="Произвольные данные клиента.")
    webhook_url: HttpUrl = Field(description="URL для уведомления о результате.")


class PaymentAcceptedResponse(BaseModel):
    """Ответ ``202 Accepted``: платёж принят в обработку."""

    payment_id: UUID
    status: PaymentStatus
    created_at: datetime

    @classmethod
    def from_acceptance(cls, acceptance: PaymentAcceptance) -> Self:
        """Строит ответ из результата команды."""
        return cls(payment_id=acceptance.payment_id, status=acceptance.status, created_at=acceptance.created_at)


class PaymentResponse(BaseModel):
    """Детальная информация о платеже."""

    payment_id: UUID
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

    @classmethod
    def from_details(cls, details: PaymentDetails) -> Self:
        """Строит ответ из проекции."""
        return cls(
            payment_id=details.id,
            amount=details.amount,
            currency=details.currency,
            description=details.description,
            metadata=details.metadata,
            status=details.status,
            idempotency_key=details.idempotency_key,
            webhook_url=details.webhook_url,
            created_at=details.created_at,
            processed_at=details.processed_at,
            webhook_delivered_at=details.webhook_delivered_at,
        )


class ErrorResponse(BaseModel):
    """Единый формат ошибки."""

    code: str
    detail: str
