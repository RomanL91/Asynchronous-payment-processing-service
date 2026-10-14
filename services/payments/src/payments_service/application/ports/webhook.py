"""Порт отправки webhook-уведомлений клиенту."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from payments_service.domain import Payment


class WebhookDeliveryError(Exception):
    """Базовая ошибка доставки webhook."""


class WebhookTemporarilyUnavailableError(WebhookDeliveryError):
    """Временная ошибка (сеть, таймаут, 5xx, 408, 429) — имеет смысл повторить."""


class WebhookPermanentlyRejectedError(WebhookDeliveryError):
    """Клиент отверг уведомление (прочие 4xx) — повтор бессмыслен."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebhookNotification:
    """Уведомление о результате обработки платежа.

    ``payment_id`` одновременно служит ключом идемпотентности для
    клиента: доставка at-least-once, и получатель должен уметь
    отбрасывать повторы.
    """

    url: str
    payment_id: UUID
    status: str
    amount: str
    currency: str
    metadata: dict[str, Any]
    processed_at: datetime | None

    @classmethod
    def from_payment(cls, payment: Payment) -> Self:
        """Строит уведомление из агрегата."""
        return cls(
            url=payment.webhook_url,
            payment_id=payment.id,
            status=payment.status.value,
            amount=payment.money.normalized_amount(),
            currency=payment.money.currency.value,
            metadata=payment.metadata,
            processed_at=payment.processed_at,
        )

    def body(self) -> dict[str, Any]:
        """JSON-тело запроса."""
        return {
            "event": "payment.processed",
            "payment_id": str(self.payment_id),
            "status": self.status,
            "amount": self.amount,
            "currency": self.currency,
            "metadata": self.metadata,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }


class WebhookSender(ABC):
    """Отправитель уведомлений."""

    @abstractmethod
    async def send(self, notification: WebhookNotification) -> None:
        """Доставляет уведомление.

        :raises WebhookTemporarilyUnavailableError: временный сбой.
        :raises WebhookPermanentlyRejectedError: клиент отверг запрос.
        """
