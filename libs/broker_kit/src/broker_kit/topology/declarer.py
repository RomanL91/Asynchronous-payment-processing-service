"""Идемпотентное объявление топологии в RabbitMQ."""

import logging
from collections.abc import Iterable

from faststream.rabbit import RabbitBroker

from broker_kit.topology.work_queue import WorkQueueTopology


class TopologyDeclarer:
    """Объявляет обменники, очереди и привязки.

    Объявления в AMQP идемпотентны при совпадении аргументов, поэтому
    каждый сервис при старте объявляет **всю** топологию. Это снимает
    гонку запуска: если relay начнёт публиковать раньше, чем поднимется
    процессор, очередь уже существует и сообщение не потеряется.
    """

    def __init__(
        self,
        broker: RabbitBroker,
        topologies: Iterable[WorkQueueTopology],
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости.

        :param broker: подключённый (или подключаемый) брокер.
        :param topologies: описания рабочих очередей.
        :param logger: логгер.
        """
        self._broker = broker
        self._topologies = tuple(topologies)
        self._logger = logger or logging.getLogger(__name__)

    async def declare(self) -> None:
        """Объявляет всё описанное в брокере."""
        for topology in self._topologies:
            await self._declare_one(topology)

    async def _declare_one(self, topology: WorkQueueTopology) -> None:
        """Объявляет одну рабочую очередь со вспомогательными."""
        exchange = await self._broker.declare_exchange(topology.exchange())
        dead_letter_exchange = await self._broker.declare_exchange(topology.dead_letter_exchange())

        main_queue = await self._broker.declare_queue(topology.main_queue())
        await main_queue.bind(exchange, routing_key=topology.routing_key)

        dead_letter_queue = await self._broker.declare_queue(topology.dead_letter_queue())
        await dead_letter_queue.bind(dead_letter_exchange, routing_key=topology.queue_name)

        for retry_queue in topology.retry_queues():
            await self._broker.declare_queue(retry_queue)

        self._logger.info(
            "Топология объявлена: %s (+%d retry, DLQ %s)",
            topology.queue_name,
            len(topology.retry_delays_ms),
            topology.dead_letter_queue_name,
        )
