"""Входящий адаптер: ``payment.created.v1`` → команда обработки."""

from broker_kit.contracts import PaymentCreatedV1
from broker_kit.observability import TraceTags
from broker_kit.reliability import InboundMessage, MessageHandler
from processor_service.application import ProcessPaymentCommand, ProcessPaymentHandler


class PaymentCreatedMessageHandler(MessageHandler):
    """Разбирает событие и запускает сценарий."""

    def __init__(self, command_handler: ProcessPaymentHandler) -> None:
        """:param command_handler: сценарий обработки платежа."""
        self._command_handler = command_handler

    async def handle(self, message: InboundMessage) -> None:
        """Обрабатывает сообщение; невалидное тело — постоянная ошибка политики."""
        event = PaymentCreatedV1.model_validate_json(message.body)
        TraceTags.tag_payment(event.payment_id)
        await self._command_handler.handle(
            ProcessPaymentCommand(
                payment_id=event.payment_id,
                amount=event.amount,
                currency=event.currency,
                description=event.description,
            )
        )
