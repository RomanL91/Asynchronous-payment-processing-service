"""Сборка FastStream-приложения consumer результатов."""

from faststream import FastStream

from broker_kit.observability import LoggingConfigurator, TracingConfigurator
from broker_kit.settings import BrokerSettings
from payments_service.bootstrap import PaymentsContainer
from payments_service.config import PaymentsSettings


class ConsumerApplicationFactory:
    """Строит приложение подписчика ``payments.processed``.

    При старте: подключение к брокеру → объявление всей топологии →
    запуск подписчика. При остановке FastStream дожидается текущих
    обработчиков (graceful timeout), затем закрываются пул БД и HTTP-клиент.
    """

    def __init__(self, settings: PaymentsSettings | None = None, broker_settings: BrokerSettings | None = None) -> None:
        """Сохраняет настройки (по умолчанию — из окружения)."""
        self._settings = settings or PaymentsSettings()
        self._broker_settings = broker_settings or BrokerSettings()

    def create(self) -> FastStream:
        """Создаёт приложение."""
        logger = LoggingConfigurator("payments-consumer", self._settings.log_level).configure()
        TracingConfigurator("payments-consumer").configure()
        container = PaymentsContainer(self._settings, self._broker_settings, logger)
        container.processed_payments_subscription.register()

        async def declare_topology() -> None:
            """Подключается и объявляет топологию до старта подписчиков."""
            await container.broker.connect()
            await container.topology_declarer.declare()

        return FastStream(
            container.broker,
            logger=logger,
            on_startup=[declare_topology],
            after_shutdown=[container.aclose],
        )
