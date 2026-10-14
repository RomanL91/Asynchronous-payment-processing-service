"""Абстракции входящего сообщения и его обработчика.

Протоколы отделяют политику надёжности от FastStream: исполнитель
работает с любым объектом, похожим на ``RabbitMessage``, что делает его
тестируемым без брокера (принцип инверсии зависимостей).
"""

from collections.abc import Mapping
from typing import Any, Protocol


class InboundMessage(Protocol):
    """Минимальный интерфейс входящего AMQP-сообщения."""

    body: bytes
    headers: Mapping[str, Any]
    message_id: str | None
    content_type: str | None

    async def ack(self) -> None:
        """Подтвердить успешную обработку."""

    async def nack(self, requeue: bool = True) -> None:
        """Отрицательно подтвердить, по умолчанию с возвратом в очередь."""

    async def reject(self, requeue: bool = False) -> None:
        """Отклонить; без requeue сообщение уходит в DLX очереди."""


class MessageHandler(Protocol):
    """Прикладной обработчик тела сообщения.

    Обработчик не управляет подтверждением: он либо завершается успешно,
    либо бросает исключение, а решение принимает исполнитель.
    """

    async def handle(self, message: InboundMessage) -> None:
        """Обработать сообщение.

        :param message: входящее сообщение.
        :raises Exception: любая ошибка обработки.
        """
