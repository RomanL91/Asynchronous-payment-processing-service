"""Фабрика брокера RabbitMQ с едиными гарантиями доставки."""

import logging

from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker
from faststream.rabbit.opentelemetry import RabbitTelemetryMiddleware

from broker_kit.settings import BrokerSettings


class RabbitBrokerFactory:
    """Собирает ``RabbitBroker`` с настройками надёжности.

    Что включается для всех сервисов:

    * **publisher confirms** — ``publish`` возвращает управление только
      после подтверждения брокером, что сообщение принято;
    * **on_return_raises** — неспособное к маршрутизации сообщение
      (нет привязанной очереди) приводит к исключению, а не теряется молча;
    * **prefetch_count** — ограничение in-flight сообщений на канал;
    * **AckPolicy.MANUAL** — подтверждением управляет наш
      ``ReliableMessageExecutor``, а не фреймворк;
    * **OpenTelemetry** — спаны публикации/обработки и передача контекста
      в заголовке ``traceparent``; при выключенной трассировке — no-op.
    """

    def __init__(self, settings: BrokerSettings, logger: logging.Logger | None = None) -> None:
        """Сохраняет настройки.

        :param settings: параметры подключения и QoS.
        :param logger: логгер FastStream; по умолчанию — ``faststream``.
        """
        self._settings = settings
        self._logger = logger or logging.getLogger("faststream")

    def create(self) -> RabbitBroker:
        """Создаёт неподключённый брокер.

        :return: экземпляр брокера; подключение выполняет приложение.
        """
        return RabbitBroker(
            self._settings.url,
            default_channel=Channel(
                prefetch_count=self._settings.prefetch_count,
                publisher_confirms=True,
                on_return_raises=True,
            ),
            ack_policy=AckPolicy.MANUAL,
            logger=self._logger,
            middlewares=(RabbitTelemetryMiddleware(),),
        )
