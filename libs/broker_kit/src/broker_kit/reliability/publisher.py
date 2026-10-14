"""Публикация копии сообщения в retry-очередь."""

from collections.abc import Mapping
from typing import Any

from faststream.rabbit import RabbitBroker, RabbitQueue

from broker_kit.contracts.headers import MessageHeaders
from broker_kit.reliability.attempts import DeliveryAttempt
from broker_kit.reliability.message import InboundMessage


class RetryPublisher:
    """Перепубликует сообщение в retry-очередь через default exchange.

    Тело и ``message_id`` сохраняются без изменений — это важно для
    идемпотентности потребителя и сквозной трассировки.
    """

    _MAX_ERROR_LENGTH = 512

    def __init__(self, broker: RabbitBroker) -> None:
        """Сохраняет брокер.

        :param broker: подключённый брокер с publisher confirms.
        """
        self._broker = broker

    async def publish(
        self,
        message: InboundMessage,
        queue: RabbitQueue,
        attempt: DeliveryAttempt,
        error: BaseException,
    ) -> None:
        """Публикует копию сообщения и дожидается подтверждения брокера.

        :param message: исходное сообщение.
        :param queue: retry-очередь нужного уровня.
        :param attempt: номер попытки, которой будет обработана копия.
        :param error: ошибка, вызвавшая ретрай.
        """
        await self._broker.publish(
            message.body,
            queue=queue.name,
            headers=self._headers(message.headers, attempt, error),
            message_id=message.message_id,
            content_type=message.content_type or "application/json",
            persist=True,
        )

    def _headers(
        self,
        original: Mapping[str, Any],
        attempt: DeliveryAttempt,
        error: BaseException,
    ) -> dict[str, Any]:
        """Строит заголовки копии: исходные + номер попытки + причина."""
        description = f"{type(error).__name__}: {error}"[: self._MAX_ERROR_LENGTH]
        return {**original, **attempt.as_header(), MessageHeaders.LAST_ERROR: description}
