"""Жизненный цикл процесса outbox relay."""

import asyncio
import signal
from contextlib import AsyncExitStack

from broker_kit.observability import LoggingConfigurator, TracingConfigurator
from broker_kit.settings import BrokerSettings
from payments_service.bootstrap import PaymentsContainer
from payments_service.config import PaymentsSettings


class RelayApplication:
    """Запускает ``OutboxRelayWorker`` и корректно останавливает его.

    SIGTERM/SIGINT устанавливают ``asyncio.Event``; цикл relay завершает
    текущую пачку (транзакция фиксируется или откатывается целиком) и
    выходит. Ресурсы освобождаются в обратном порядке через ``AsyncExitStack``.
    """

    _STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)

    def __init__(self, settings: PaymentsSettings | None = None, broker_settings: BrokerSettings | None = None) -> None:
        """Сохраняет настройки (по умолчанию — из окружения)."""
        self._settings = settings or PaymentsSettings()
        self._broker_settings = broker_settings or BrokerSettings()

    async def run(self) -> None:
        """Работает до сигнала остановки."""
        logger = LoggingConfigurator("payments-relay", self._settings.log_level).configure()
        TracingConfigurator("payments-relay").configure()
        container = PaymentsContainer(self._settings, self._broker_settings, logger)
        stop = self._install_signal_handlers()

        async with AsyncExitStack() as resources:
            resources.push_async_callback(container.aclose)
            await container.broker.connect()
            resources.push_async_callback(container.broker.stop)
            await container.topology_declarer.declare()
            await container.outbox_relay_worker.run(stop)

    def _install_signal_handlers(self) -> asyncio.Event:
        """Переводит сигналы ОС в событие остановки."""
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for stop_signal in self._STOP_SIGNALS:
            loop.add_signal_handler(stop_signal, stop.set)
        return stop
