"""Outbox relay: доставка записей outbox в RabbitMQ.

Гарантия — at-least-once. Сообщение помечается опубликованным только
после publisher confirm; если процесс упадёт между confirm и ``COMMIT``,
сообщение будет опубликовано повторно — дубль погасят идемпотентные
потребители (по ``message_id`` / ``payment_id``).
"""

from payments_service.infrastructure.outbox.publisher import RabbitOutboxPublisher
from payments_service.infrastructure.outbox.relay import OutboxRelay, OutboxRelayWorker
from payments_service.infrastructure.outbox.routing import EventRoute, EventRoutingTable

__all__ = ["EventRoute", "EventRoutingTable", "OutboxRelay", "OutboxRelayWorker", "RabbitOutboxPublisher"]
