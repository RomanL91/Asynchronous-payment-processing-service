"""Доставка webhook-уведомления о результате платежа."""

import logging

from payments_service.application.ports import Clock, UnitOfWorkFactory, WebhookNotification, WebhookSender
from payments_service.domain import Payment


class DeliverWebhookHandler:
    """Отправляет уведомление и фиксирует факт доставки.

    Гарантия — at-least-once: если упасть после ответа клиента, но до
    отметки ``webhook_delivered_at``, уведомление уйдёт повторно.
    Получатель дедуплицирует по ``payment_id`` (заголовок ``Idempotency-Key``).
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        sender: WebhookSender,
        clock: Clock,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._uow_factory = uow_factory
        self._sender = sender
        self._clock = clock
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, payment: Payment) -> None:
        """Доставляет уведомление, если оно ещё не доставлено.

        :param payment: платёж в окончательном статусе.
        :raises WebhookDeliveryError: ошибка доставки (классифицирована).
        """
        if not payment.awaits_webhook:
            self._logger.debug("Webhook по платежу %s не требуется", payment.id)
            return

        await self._sender.send(WebhookNotification.from_payment(payment))

        if payment.mark_webhook_delivered(self._clock.now()):
            async with self._uow_factory() as uow:
                await uow.payments.update(payment)
                await uow.commit()
        self._logger.info("Webhook по платежу %s доставлен на %s", payment.id, payment.webhook_url)
