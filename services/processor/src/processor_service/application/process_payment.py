"""Сценарий обработки платежа."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from uuid import UUID

from broker_kit.contracts import PaymentProcessedV1, ProcessingStatus
from processor_service.application.ports import PaymentGateway, ProcessingResultPublisher
from processor_service.domain import ChargeOutcome, ChargeRequest, ChargeStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessPaymentCommand:
    """Платёж, который нужно провести."""

    payment_id: UUID
    amount: Decimal
    currency: str
    description: str


class ResultEventFactory:
    """Строит событие-контракт из ответа шлюза (anti-corruption на выходе)."""

    _STATUSES = MappingProxyType(
        {ChargeStatus.SUCCEEDED: ProcessingStatus.SUCCEEDED, ChargeStatus.FAILED: ProcessingStatus.FAILED}
    )

    def create(self, payment_id: UUID, outcome: ChargeOutcome) -> PaymentProcessedV1:
        """Событие ``payment.processed.v1``."""
        return PaymentProcessedV1(
            payment_id=payment_id,
            status=self._STATUSES[outcome.status],
            gateway_charge_id=outcome.charge_id,
            processed_at=outcome.processed_at,
        )


class ProcessPaymentHandler:
    """Провести платёж через шлюз и опубликовать результат.

    Обработчик не хранит состояния и безопасен при повторной доставке:

    * повторный вызов шлюза с тем же ``Idempotency-Key`` не списывает
      деньги второй раз, а возвращает сохранённый результат;
    * повторная публикация того же результата гасится у владельца
      платежа (переход статуса разрешён только из ``pending``).

    Отказ шлюза в списании (10%) — **бизнес-результат** ``failed``, а не
    ошибка: он публикуется как обычный результат и не ретраится.
    """

    def __init__(
        self,
        gateway: PaymentGateway,
        publisher: ProcessingResultPublisher,
        events: ResultEventFactory | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._gateway = gateway
        self._publisher = publisher
        self._events = events or ResultEventFactory()
        self._logger = logger or logging.getLogger(__name__)

    async def handle(self, command: ProcessPaymentCommand) -> ChargeOutcome:
        """Проводит платёж.

        :raises GatewayUnavailableError: шлюз временно недоступен.
        :raises GatewayRejectedError: шлюз отверг запрос.
        """
        outcome = await self._gateway.charge(
            ChargeRequest(
                idempotency_key=str(command.payment_id),
                amount=command.amount,
                currency=command.currency,
                description=command.description,
            )
        )
        await self._publisher.publish(self._events.create(command.payment_id, outcome))
        self._logger.info(
            "Платёж %s обработан: %s (charge %s%s)",
            command.payment_id,
            outcome.status,
            outcome.charge_id,
            ", повтор у шлюза" if outcome.replayed else "",
        )
        return outcome
