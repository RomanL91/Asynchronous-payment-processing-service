"""Входящий адаптер: сообщение ``payment.processed.v1`` → команда."""

from types import MappingProxyType

from broker_kit.contracts import PaymentProcessedV1, ProcessingStatus
from broker_kit.observability import TraceTags
from broker_kit.reliability import InboundMessage, MessageHandler
from payments_service.application.commands import ApplyProcessingResultCommand, ApplyProcessingResultHandler
from payments_service.domain import PaymentStatus


class ProcessingStatusTranslator:
    """Anti-corruption layer: статус контракта → доменный статус.

    Контракт и домен эволюционируют независимо; связь между ними —
    только эта таблица.
    """

    _MAPPING = MappingProxyType(
        {
            ProcessingStatus.SUCCEEDED: PaymentStatus.SUCCEEDED,
            ProcessingStatus.FAILED: PaymentStatus.FAILED,
        }
    )

    def translate(self, status: ProcessingStatus) -> PaymentStatus:
        """Возвращает доменный статус."""
        return self._MAPPING[status]


class PaymentProcessedMessageHandler(MessageHandler):
    """Разбирает тело события и вызывает прикладную команду.

    Ошибка валидации тела — постоянная (ядовитое сообщение → DLQ);
    решение принимает политика ``broker_kit``, а не этот класс.
    """

    def __init__(
        self,
        command_handler: ApplyProcessingResultHandler,
        translator: ProcessingStatusTranslator | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._command_handler = command_handler
        self._translator = translator or ProcessingStatusTranslator()

    async def handle(self, message: InboundMessage) -> None:
        """Обрабатывает сообщение."""
        event = PaymentProcessedV1.model_validate_json(message.body)
        TraceTags.tag_payment(event.payment_id)
        await self._command_handler.handle(
            ApplyProcessingResultCommand(
                payment_id=event.payment_id,
                outcome=self._translator.translate(event.status),
                processed_at=event.processed_at,
            )
        )
