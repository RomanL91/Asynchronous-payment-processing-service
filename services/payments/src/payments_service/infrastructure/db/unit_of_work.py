"""Unit of Work на SQLAlchemy."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from payments_service.application.ports import UnitOfWork
from payments_service.infrastructure.db.database import Database
from payments_service.infrastructure.db.repositories import SqlAlchemyOutboxRepository, SqlAlchemyPaymentRepository


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Одна сессия = одна транзакция; репозитории разделяют её.

    Благодаря общей сессии платёж и сообщение outbox попадают в один
    ``COMMIT`` — на этом и держится гарантия outbox-паттерна.
    """

    def __init__(self, database: Database) -> None:
        """:param database: источник сессий."""
        self._database = database
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        """Открывает сессию и создаёт репозитории."""
        self._session = self._database.session()
        self.payments = SqlAlchemyPaymentRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Откатывает незафиксированное и закрывает сессию."""
        try:
            await super().__aexit__(exc_type, exc, traceback)
        finally:
            await self._require_session().close()
            self._session = None

    async def commit(self) -> None:
        """Фиксирует транзакцию."""
        await self._require_session().commit()

    async def rollback(self) -> None:
        """Откатывает транзакцию (no-op, если она уже зафиксирована)."""
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        """Сессия доступна только внутри ``async with``."""
        if self._session is None:
            raise RuntimeError("Unit of Work используется вне async with")
        return self._session
