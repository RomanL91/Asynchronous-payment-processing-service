"""Порты сценария списания."""

from abc import ABC, abstractmethod

from gateway_mock.domain import Charge


class ChargeStore(ABC):
    """Хранилище проведённых списаний по ключу идемпотентности."""

    @abstractmethod
    async def get(self, idempotency_key: str) -> Charge | None:
        """Списание по ключу или ``None``."""

    @abstractmethod
    async def save(self, charge: Charge) -> None:
        """Сохраняет списание."""
