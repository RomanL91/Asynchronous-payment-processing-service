"""Регистрация надёжного подписчика в FastStream."""

from faststream import AckPolicy
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage

from broker_kit.reliability.executor import ReliableMessageExecutor
from broker_kit.reliability.message import MessageHandler
from broker_kit.topology.work_queue import WorkQueueTopology


class ReliableSubscription:
    """Связывает рабочую очередь, обработчик и исполнитель (Facade).

    FastStream получает сырое сообщение без автоматического разбора
    тела: разбор выполняет обработчик, и ошибка валидации становится
    «постоянной ошибкой» политики, а не исключением фреймворка.

    Конкурентность: aiormq запускает отдельную задачу event loop на
    каждое доставленное сообщение, поэтому одновременно обрабатывается
    до ``prefetch_count`` сообщений канала.
    """

    def __init__(
        self,
        broker: RabbitBroker,
        topology: WorkQueueTopology,
        handler: MessageHandler,
        executor: ReliableMessageExecutor,
    ) -> None:
        """Сохраняет зависимости.

        :param broker: брокер FastStream.
        :param topology: обслуживаемая очередь.
        :param handler: прикладной обработчик.
        :param executor: исполнитель с политикой надёжности.
        """
        self._broker = broker
        self._topology = topology
        self._handler = handler
        self._executor = executor

    def register(self) -> None:
        """Регистрирует подписчика с ручным подтверждением."""
        executor, handler = self._executor, self._handler

        async def consume(message: RabbitMessage) -> None:
            """Точка входа FastStream: делегирует исполнителю."""
            await executor.execute(message, handler)

        self._broker.subscriber(
            self._topology.main_queue(),
            self._topology.exchange(),
            ack_policy=AckPolicy.MANUAL,
            title=f"{self._topology.queue_name}:consume",
        )(consume)
