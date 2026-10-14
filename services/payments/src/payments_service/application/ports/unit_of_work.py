"""Порт Unit of Work."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Protocol, Self

from payments_service.application.ports.repositories import OutboxRepository, PaymentRepository


class UnitOfWork(ABC):
    """Граница транзакции (паттерн Unit of Work).

    Используется как асинхронный контекстный менеджер. Фиксация явная —
    ``commit()``; выход из блока без неё или с исключением откатывает
    изменения. Так незавершённая операция никогда не сохраняется
    «случайно».
    """

    payments: PaymentRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> Self:
        """Открывает транзакцию."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Откатывает незафиксированные изменения и освобождает ресурсы."""
        await self.rollback()

    @abstractmethod
    async def commit(self) -> None:
        """Фиксирует транзакцию."""

    @abstractmethod
    async def rollback(self) -> None:
        """Откатывает транзакцию (безопасно после commit)."""


class UnitOfWorkFactory(Protocol):
    """Фабрика: каждый сценарий получает свежий Unit of Work."""

    def __call__(self) -> UnitOfWork:
        """Создаёт новый Unit of Work."""
