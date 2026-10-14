"""Исполнитель обработки сообщения с политикой надёжности (Template Method)."""

import logging
from typing import Final

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from broker_kit.reliability.attempts import DeliveryAttempt
from broker_kit.reliability.message import InboundMessage, MessageHandler
from broker_kit.reliability.policy import FailureContext, FailurePolicy
from broker_kit.topology.work_queue import WorkQueueTopology


class ReliableMessageExecutor:
    """Выполняет обработчик и единообразно завершает доставку.

    Фиксированный алгоритм (Template Method): вызвать обработчик →
    ``ack`` при успехе → при ошибке спросить политику и применить
    действие. Сам обработчик об ack/nack ничего не знает (SRP).

    ``asyncio.CancelledError`` намеренно не перехватывается (это
    ``BaseException``): при остановке сервиса сообщение остаётся
    неподтверждённым и будет доставлено снова после переподключения.
    """

    OUTCOME_ATTRIBUTE: Final[str] = "messaging.failure.outcome"
    """Атрибут спана с исходом упавшей попытки: уход в DLQ делает брокер
    (reject → DLX), отдельного спана публикации у него нет."""

    def __init__(
        self,
        topology: WorkQueueTopology,
        policy: FailurePolicy,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости.

        :param topology: очередь, которую обслуживает исполнитель.
        :param policy: политика реакции на ошибки.
        :param logger: логгер.
        """
        self._topology = topology
        self._policy = policy
        self._logger = logger or logging.getLogger(__name__)

    async def execute(self, message: InboundMessage, handler: MessageHandler) -> None:
        """Обрабатывает сообщение и подтверждает либо перенаправляет его.

        :param message: входящее сообщение.
        :param handler: прикладной обработчик.
        """
        attempt = DeliveryAttempt.from_headers(message.headers)
        try:
            await handler.handle(message)
        except Exception as error:
            self._mark_span_failed(error)
            await self._on_failure(message, error, attempt)
        else:
            await message.ack()

    @staticmethod
    def _mark_span_failed(error: Exception) -> None:
        """Отмечает спан обработки ошибкой: исключение перехвачено здесь, middleware его не видит."""
        span = trace.get_current_span()
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, f"{type(error).__name__}: {error}"))

    async def _on_failure(
        self,
        message: InboundMessage,
        error: Exception,
        attempt: DeliveryAttempt,
    ) -> None:
        """Применяет действие политики; при его сбое возвращает сообщение в очередь."""
        action = self._policy.resolve(FailureContext(error=error, attempt=attempt, topology=self._topology))
        trace.get_current_span().set_attribute(self.OUTCOME_ATTRIBUTE, action.describe())
        self._logger.warning(
            "Сообщение %s из %s, попытка %d/%d: %s: %s → %s",
            message.message_id,
            self._topology.queue_name,
            attempt.number,
            self._topology.max_attempts,
            type(error).__name__,
            error,
            action.describe(),
        )
        try:
            await action.apply(message)
        except Exception:
            self._logger.exception(
                "Не удалось применить действие к %s, возвращаем в очередь",
                message.message_id,
            )
            await message.nack(requeue=True)
