"""Маршрутизация интеграционных событий по типу."""

from dataclasses import dataclass
from typing import Self

from faststream.rabbit import RabbitExchange

from broker_kit.contracts import PaymentCreatedV1
from broker_kit.topology import PaymentsTopology


class UnknownEventTypeError(LookupError):
    """Для типа события не задан маршрут."""


@dataclass(frozen=True, slots=True)
class EventRoute:
    """Куда публиковать событие."""

    exchange: RabbitExchange
    routing_key: str


class EventRoutingTable:
    """Таблица ``event_type → маршрут`` (Registry).

    Outbox хранит только тип события, а не адрес: топологию можно
    менять без миграции накопленных записей.
    """

    def __init__(self, routes: dict[str, EventRoute]) -> None:
        """:param routes: маршруты по типам событий."""
        self._routes = dict(routes)

    @classmethod
    def from_topology(cls, topology: PaymentsTopology) -> Self:
        """Маршруты событий, публикуемых payments-service."""
        new_payments = topology.new_payments
        return cls({PaymentCreatedV1.event_type: EventRoute(new_payments.exchange(), new_payments.routing_key)})

    def resolve(self, event_type: str) -> EventRoute:
        """Возвращает маршрут.

        :raises UnknownEventTypeError: маршрут не зарегистрирован.
        """
        try:
            return self._routes[event_type]
        except KeyError as error:
            raise UnknownEventTypeError(f"Нет маршрута для события {event_type!r}") from error
