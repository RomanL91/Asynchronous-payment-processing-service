"""Порт платёжного шлюза."""

from abc import ABC, abstractmethod

from processor_service.domain import ChargeOutcome, ChargeRequest


class GatewayError(Exception):
    """Базовая ошибка взаимодействия со шлюзом."""


class GatewayUnavailableError(GatewayError):
    """Шлюз временно недоступен (сеть, таймаут, 5xx, 429) — повторить."""


class GatewayRejectedError(GatewayError):
    """Шлюз отверг запрос как некорректный (4xx) — повтор бессмыслен."""


class PaymentGateway(ABC):
    """Внешний платёжный шлюз с поддержкой идемпотентности."""

    @abstractmethod
    async def charge(self, request: ChargeRequest) -> ChargeOutcome:
        """Проводит списание или возвращает результат уже проведённого.

        :raises GatewayUnavailableError: временный сбой.
        :raises GatewayRejectedError: запрос отклонён.
        """
