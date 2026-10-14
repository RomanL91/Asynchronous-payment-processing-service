"""Преобразование доменных событий в сообщения outbox."""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from uuid import UUID

from broker_kit.contracts import IntegrationEvent, PaymentCreatedV1
from payments_service.application.outbox import OutboxMessage
from payments_service.application.ports import IdGenerator
from payments_service.domain import DomainEvent, PaymentRegistered


class EventTranslator[EventT: DomainEvent](ABC):
    """Переводчик одного типа доменного события (Strategy)."""

    @abstractmethod
    def aggregate_id(self, event: EventT) -> UUID:
        """Идентификатор агрегата-источника."""

    @abstractmethod
    def translate(self, event: EventT) -> IntegrationEvent:
        """Строит интеграционное событие-контракт."""


class PaymentRegisteredTranslator(EventTranslator[PaymentRegistered]):
    """``PaymentRegistered`` → ``PaymentCreatedV1``."""

    def aggregate_id(self, event: PaymentRegistered) -> UUID:
        """Идентификатор платежа."""
        return event.payment_id

    def translate(self, event: PaymentRegistered) -> IntegrationEvent:
        """Переносит в контракт всё, что нужно процессору."""
        return PaymentCreatedV1(
            payment_id=event.payment_id,
            amount=event.money.amount,
            currency=event.money.currency.value,
            description=event.description,
            created_at=event.occurred_at,
        )


class OutboxMessageMapper:
    """Реестр переводчиков: тип доменного события → переводчик.

    Новое событие добавляется регистрацией переводчика, без правки
    существующего кода (OCP). Доменные события без переводчика —
    внутренние и наружу не публикуются.
    """

    _DEFAULT_TRANSLATORS: Mapping[type[DomainEvent], EventTranslator] = MappingProxyType(
        {PaymentRegistered: PaymentRegisteredTranslator()}
    )

    def __init__(
        self,
        ids: IdGenerator,
        translators: Mapping[type[DomainEvent], EventTranslator] | None = None,
    ) -> None:
        """Сохраняет зависимости.

        :param ids: генератор идентификаторов сообщений.
        :param translators: реестр; по умолчанию — переводчики сервиса.
        """
        self._ids = ids
        self._translators = translators or self._DEFAULT_TRANSLATORS

    def to_outbox(self, events: Iterable[DomainEvent]) -> list[OutboxMessage]:
        """Переводит публикуемые события в сообщения outbox."""
        return [self._map(event, translator) for event in events if (translator := self._translators.get(type(event)))]

    def _map(self, event: DomainEvent, translator: EventTranslator) -> OutboxMessage:
        """Строит одно сообщение outbox."""
        integration_event = translator.translate(event)
        return OutboxMessage(
            id=self._ids.new_id(),
            aggregate_id=translator.aggregate_id(event),
            event_type=integration_event.event_type,
            payload=integration_event.model_dump(mode="json"),
            created_at=event.occurred_at,
        )
