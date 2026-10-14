"""Команда применения результата обработки от процессора."""

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from payments_service.application.commands.deliver_webhook import DeliverWebhookHandler
from payments_service.application.exceptions import PaymentNotFoundError
from payments_service.application.ports import UnitOfWorkFactory
from payments_service.domain import OutcomeResolution, Payment, PaymentStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyProcessingResultCommand:
    """Результат обработки платежа шлюзом."""

    payment_id: UUID
    outcome: PaymentStatus
    processed_at: datetime


class ApplyProcessingResultHandler:
    """Фиксирует результат (первый побеждает) и уведомляет клиента.

    Шаги разнесены по разным транзакциям намеренно:

    1. ``SELECT … FOR UPDATE`` → переход статуса → ``COMMIT``. Блокировка
       сериализует конкурентные дубли: второй увидит окончательный статус.
    2. HTTP-вызов webhook — **вне** транзакции, чтобы не держать строку
       и соединение пула на время сетевого запроса.

    Если упасть между шагами, повторная доставка сообщения увидит
    окончательный статус без ``webhook_delivered_at`` и доотправит
    уведомление — шаги идемпотентны по отдельности.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        webhook_delivery: DeliverWebhookHandler,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._uow_factory = uow_factory
        self._webhook_delivery = webhook_delivery
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, command: ApplyProcessingResultCommand) -> OutcomeResolution:
        """Применяет результат и доставляет webhook при необходимости.

        :raises PaymentNotFoundError: платёж неизвестен (постоянная ошибка).
        """
        payment, resolution = await self._apply(command)
        self._log(payment, command, resolution)
        await self._webhook_delivery.handle(payment)
        return resolution

    async def _apply(self, command: ApplyProcessingResultCommand) -> tuple[Payment, OutcomeResolution]:
        """Транзакционно переводит статус платежа."""
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_for_update(command.payment_id)
            if payment is None:
                raise PaymentNotFoundError(command.payment_id)
            resolution = payment.apply_outcome(command.outcome, command.processed_at)
            if resolution.changed_state:
                await uow.payments.update(payment)
                await uow.commit()
        return payment, resolution

    def _log(self, payment: Payment, command: ApplyProcessingResultCommand, resolution: OutcomeResolution) -> None:
        """Пишет в лог исход применения результата."""
        level = logging.WARNING if resolution is OutcomeResolution.CONFLICT else logging.INFO
        self._logger.log(
            level,
            "Платёж %s: результат %s → %s (текущий статус %s)",
            payment.id,
            command.outcome,
            resolution,
            payment.status,
        )
