"""Порты прикладного слоя — абстракции, реализуемые инфраструктурой."""

from payments_service.application.ports.readers import PaymentReader
from payments_service.application.ports.repositories import OutboxRepository, PaymentRepository
from payments_service.application.ports.system import Clock, IdGenerator
from payments_service.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from payments_service.application.ports.webhook import (
    WebhookDeliveryError,
    WebhookNotification,
    WebhookPermanentlyRejectedError,
    WebhookSender,
    WebhookTemporarilyUnavailableError,
)

__all__ = [
    "Clock",
    "IdGenerator",
    "OutboxRepository",
    "PaymentReader",
    "PaymentRepository",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "WebhookDeliveryError",
    "WebhookNotification",
    "WebhookPermanentlyRejectedError",
    "WebhookSender",
    "WebhookTemporarilyUnavailableError",
]
