"""Публикация сообщения outbox в RabbitMQ."""

import json
from abc import ABC, abstractmethod

from faststream.rabbit import RabbitBroker

from broker_kit.contracts import MessageHeaders
from payments_service.application.outbox import OutboxMessage
from payments_service.infrastructure.outbox.routing import EventRoutingTable


class OutboxPublisher(ABC):
    """Порт публикации для relay."""

    @abstractmethod
    async def publish(self, message: OutboxMessage) -> None:
        """Публикует сообщение и возвращается после подтверждения брокера."""


class RabbitOutboxPublisher(OutboxPublisher):
    """Публикует в RabbitMQ с persistent-доставкой.

    * ``message_id`` = id записи outbox — сквозной идентификатор для
      дедупликации и трассировки;
    * ``persist=True`` (delivery_mode=2) — сообщение переживёт рестарт
      брокера в durable-очереди;
    * publisher confirms включены на канале (``RabbitBrokerFactory``).
    """

    def __init__(self, broker: RabbitBroker, routing: EventRoutingTable) -> None:
        """:param broker: подключённый брокер. :param routing: таблица маршрутов."""
        self._broker = broker
        self._routing = routing

    async def publish(self, message: OutboxMessage) -> None:
        """Публикует сообщение и дожидается confirm."""
        route = self._routing.resolve(message.event_type)
        await self._broker.publish(
            json.dumps(message.payload, ensure_ascii=False).encode(),
            exchange=route.exchange,
            routing_key=route.routing_key,
            message_id=str(message.id),
            correlation_id=str(message.aggregate_id),
            headers={MessageHeaders.EVENT_TYPE: message.event_type},
            content_type="application/json",
            timestamp=message.created_at,
            persist=True,
        )
