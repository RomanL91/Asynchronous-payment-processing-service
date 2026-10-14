"""Публикация ``payment.processed.v1``."""

import uuid

from faststream.rabbit import RabbitBroker

from broker_kit.contracts import MessageHeaders, PaymentProcessedV1
from broker_kit.topology import WorkQueueTopology
from processor_service.application.ports import ProcessingResultPublisher


class RabbitResultPublisher(ProcessingResultPublisher):
    """Публикует результат в обменник ``payments`` с ключом ``payment.processed``.

    ``message_id`` детерминирован (UUIDv5 от ``payment_id``): повторная
    публикация того же результата получает тот же идентификатор, что
    упрощает трассировку дублей.
    """

    _NAMESPACE = uuid.UUID("6f1c2b6e-2f4f-4a39-9d1c-5b8f0d6f6a11")

    def __init__(self, broker: RabbitBroker, topology: WorkQueueTopology) -> None:
        """:param broker: брокер с confirms. :param topology: очередь результатов."""
        self._broker = broker
        self._topology = topology

    async def publish(self, event: PaymentProcessedV1) -> None:
        """Публикует событие и ждёт publisher confirm."""
        await self._broker.publish(
            event.to_json_bytes(),
            exchange=self._topology.exchange(),
            routing_key=self._topology.routing_key,
            message_id=str(uuid.uuid5(self._NAMESPACE, f"processed:{event.payment_id}")),
            correlation_id=str(event.payment_id),
            headers={MessageHeaders.EVENT_TYPE: event.event_type},
            content_type="application/json",
            persist=True,
        )
