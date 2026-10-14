"""Интеграция надёжного подписчика с FastStream (in-memory брокер)."""

from faststream.rabbit import RabbitBroker, TestRabbitBroker
from faststream.rabbit.annotations import RabbitMessage

from broker_kit.reliability import (
    FailurePolicy,
    ReliableMessageExecutor,
    ReliableSubscription,
    RetryPublisher,
    TransientError,
    TypeBasedErrorClassifier,
)
from broker_kit.topology import WorkQueueTopology


class _FlakyHandler:
    """Падает на первой попытке, затем успешен."""

    def __init__(self) -> None:
        self.bodies: list[bytes] = []

    async def handle(self, message) -> None:
        """Запоминает тело и падает один раз."""
        self.bodies.append(message.body)
        if len(self.bodies) == 1:
            raise TransientError("первая попытка")


async def test_subscription_delivers_raw_body_and_retries(topology: WorkQueueTopology) -> None:
    """Обработчик получает сырое тело; при ошибке копия уходит в retry-очередь."""
    broker = RabbitBroker()
    handler = _FlakyHandler()
    policy = FailurePolicy.default(TypeBasedErrorClassifier(), RetryPublisher(broker))
    ReliableSubscription(broker, topology, handler, ReliableMessageExecutor(topology, policy)).register()

    retried: list[dict] = []

    @broker.subscriber(topology.retry_queue_after(1))
    async def capture_retry(body: dict, message: RabbitMessage) -> None:
        retried.append({"body": body, "attempt": message.headers.get("x-attempt")})

    async with TestRabbitBroker(broker) as test_broker:
        await test_broker.publish(
            {"payment_id": "42"},
            exchange=topology.exchange(),
            routing_key=topology.routing_key,
            message_id="m-1",
        )

    assert handler.bodies == [b'{"payment_id":"42"}']
    assert retried == [{"body": {"payment_id": "42"}, "attempt": 2}]
