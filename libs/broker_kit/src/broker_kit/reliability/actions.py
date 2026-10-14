"""Действия над упавшим сообщением (Strategy)."""

from abc import ABC, abstractmethod

from faststream.rabbit import RabbitQueue

from broker_kit.reliability.attempts import DeliveryAttempt
from broker_kit.reliability.message import InboundMessage
from broker_kit.reliability.publisher import RetryPublisher


class FailureAction(ABC):
    """Что сделать с сообщением, обработка которого завершилась ошибкой."""

    @abstractmethod
    async def apply(self, message: InboundMessage) -> None:
        """Применяет действие и завершает жизненный цикл доставки.

        :param message: упавшее сообщение.
        """

    @abstractmethod
    def describe(self) -> str:
        """Краткое описание для логов."""


class DeadLetterAction(FailureAction):
    """Отправка в DLQ средствами брокера.

    ``reject(requeue=False)`` заставляет RabbitMQ переложить сообщение в
    ``x-dead-letter-exchange`` основной очереди и добавить штатный
    заголовок ``x-death`` с причиной и временем.
    """

    def __init__(self, reason: str) -> None:
        """Сохраняет причину.

        :param reason: почему сообщение признано необрабатываемым.
        """
        self._reason = reason

    async def apply(self, message: InboundMessage) -> None:
        """Отклоняет сообщение без возврата в очередь."""
        await message.reject(requeue=False)

    def describe(self) -> str:
        """Краткое описание для логов."""
        return f"DLQ ({self._reason})"


class RetryLaterAction(FailureAction):
    """Отложенный повтор через retry-очередь с TTL."""

    def __init__(
        self,
        publisher: RetryPublisher,
        queue: RabbitQueue,
        next_attempt: DeliveryAttempt,
        error: BaseException,
    ) -> None:
        """Сохраняет параметры повтора.

        :param publisher: публикатор копий.
        :param queue: retry-очередь нужной задержки.
        :param next_attempt: номер следующей попытки.
        :param error: ошибка текущей попытки.
        """
        self._publisher = publisher
        self._queue = queue
        self._next_attempt = next_attempt
        self._error = error

    async def apply(self, message: InboundMessage) -> None:
        """Публикует копию в retry-очередь, затем подтверждает оригинал.

        Если упадём между шагами — оригинал будет доставлен повторно
        (дубль), но не потерян.
        """
        await self._publisher.publish(message, self._queue, self._next_attempt, self._error)
        await message.ack()

    def describe(self) -> str:
        """Краткое описание для логов."""
        return f"retry → {self._queue.name} (попытка {self._next_attempt.number})"
