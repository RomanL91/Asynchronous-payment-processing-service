"""Контракты межсервисного обмена.

Содержит интеграционные события (публичный API сервисов через брокер)
и имена служебных AMQP-заголовков. Изменение контракта — изменение
публичного API, поэтому события версионируются суффиксом ``V1``.
"""

from broker_kit.contracts.events import (
    IntegrationEvent,
    PaymentCreatedV1,
    PaymentProcessedV1,
    ProcessingStatus,
)
from broker_kit.contracts.headers import MessageHeaders

__all__ = [
    "IntegrationEvent",
    "MessageHeaders",
    "PaymentCreatedV1",
    "PaymentProcessedV1",
    "ProcessingStatus",
]
