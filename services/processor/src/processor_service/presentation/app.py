"""Сборка FastStream-приложения процессора."""

from faststream import FastStream

from broker_kit.observability import LoggingConfigurator, TracingConfigurator
from broker_kit.settings import BrokerSettings
from processor_service.bootstrap import ProcessorContainer
from processor_service.config import ProcessorSettings


class ProcessorApplicationFactory:
    """Подключение → объявление топологии → подписка на ``payments.new``."""

    def __init__(
        self,
        settings: ProcessorSettings | None = None,
        broker_settings: BrokerSettings | None = None,
    ) -> None:
        """Сохраняет настройки (по умолчанию — из окружения)."""
        self._settings = settings or ProcessorSettings()
        self._broker_settings = broker_settings or BrokerSettings()

    def create(self) -> FastStream:
        """Создаёт приложение."""
        logger = LoggingConfigurator("processor", self._settings.log_level).configure()
        TracingConfigurator("processor").configure()
        container = ProcessorContainer(self._settings, self._broker_settings)
        container.new_payments_subscription.register()

        async def declare_topology() -> None:
            """Объявляет топологию до старта подписчиков."""
            await container.broker.connect()
            await container.topology_declarer.declare()

        return FastStream(
            container.broker,
            logger=logger,
            on_startup=[declare_topology],
            after_shutdown=[container.aclose],
        )
