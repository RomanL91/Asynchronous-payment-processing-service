"""Отправка webhook через httpx."""

import httpx

from payments_service.application.ports import (
    WebhookNotification,
    WebhookSender,
    WebhookTemporarilyUnavailableError,
)
from payments_service.infrastructure.webhook.policy import WebhookResponsePolicy


class HttpxWebhookSender(WebhookSender):
    """POST JSON на ``webhook_url`` клиента.

    Один ``AsyncClient`` на процесс — пул keep-alive соединений
    переиспользуется между уведомлениями. Сетевые ошибки и таймауты
    считаются временными.
    """

    def __init__(self, client: httpx.AsyncClient, policy: WebhookResponsePolicy) -> None:
        """:param client: общий HTTP-клиент. :param policy: классификатор ответов."""
        self._client = client
        self._policy = policy

    async def send(self, notification: WebhookNotification) -> None:
        """Отправляет уведомление.

        Заголовок ``Idempotency-Key`` позволяет получателю отбрасывать
        повторные доставки.
        """
        try:
            response = await self._client.post(
                notification.url,
                json=notification.body(),
                headers={
                    "Idempotency-Key": str(notification.payment_id),
                    "X-Webhook-Event": "payment.processed",
                },
            )
        except httpx.HTTPError as error:
            raise WebhookTemporarilyUnavailableError(
                f"Webhook {notification.url} недоступен: {type(error).__name__}"
            ) from error
        self._policy.ensure_delivered(response.status_code, notification.url)
