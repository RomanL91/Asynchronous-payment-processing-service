"""Отображение между ORM-моделями и доменом (Data Mapper)."""

from typing import Any

from payments_service.application.outbox import OutboxMessage
from payments_service.domain import IdempotencyKey, Money, Payment, RequestFingerprint
from payments_service.infrastructure.db.models import OutboxModel, PaymentModel


class PaymentMapper:
    """Преобразует строку ``payments`` ↔ агрегат ``Payment``.

    Домен не знает об ORM: агрегат — обычный dataclass, а персистентность
    сосредоточена здесь.
    """

    def to_domain(self, row: PaymentModel) -> Payment:
        """Строит агрегат из ORM-объекта."""
        return Payment(
            id=row.id,
            idempotency_key=IdempotencyKey(row.idempotency_key),
            fingerprint=RequestFingerprint(row.request_fingerprint),
            money=Money(row.amount, row.currency),
            description=row.description,
            metadata=row.metadata_,
            webhook_url=row.webhook_url,
            status=row.status,
            created_at=row.created_at,
            processed_at=row.processed_at,
            webhook_delivered_at=row.webhook_delivered_at,
        )

    def to_insert_values(self, payment: Payment) -> dict[str, Any]:
        """Значения колонок для вставки нового платежа."""
        return {
            "id": payment.id,
            "idempotency_key": payment.idempotency_key.value,
            "request_fingerprint": payment.fingerprint.value,
            "amount": payment.money.amount,
            "currency": payment.money.currency,
            "description": payment.description,
            "metadata": payment.metadata,
            "webhook_url": payment.webhook_url,
            "created_at": payment.created_at,
            **self.to_mutable_values(payment),
        }

    def to_mutable_values(self, payment: Payment) -> dict[str, Any]:
        """Значения изменяемых колонок для ``UPDATE``."""
        return {
            "status": payment.status,
            "processed_at": payment.processed_at,
            "webhook_delivered_at": payment.webhook_delivered_at,
        }


class OutboxMapper:
    """Преобразует строку ``outbox`` ↔ ``OutboxMessage``."""

    def to_domain(self, row: OutboxModel) -> OutboxMessage:
        """Строит сообщение из ORM-объекта."""
        return OutboxMessage(
            id=row.id,
            aggregate_id=row.aggregate_id,
            event_type=row.event_type,
            payload=row.payload,
            created_at=row.created_at,
        )

    def to_insert_values(self, message: OutboxMessage) -> dict[str, Any]:
        """Значения колонок для вставки."""
        return {
            "id": message.id,
            "aggregate_id": message.aggregate_id,
            "event_type": message.event_type,
            "payload": message.payload,
            "created_at": message.created_at,
        }
