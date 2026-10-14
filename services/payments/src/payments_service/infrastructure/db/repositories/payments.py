"""Репозиторий платежей."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payments_service.application.ports import PaymentRepository
from payments_service.domain import IdempotencyKey, Payment
from payments_service.infrastructure.db.mappers import PaymentMapper
from payments_service.infrastructure.db.models import PaymentModel


class SqlAlchemyPaymentRepository(PaymentRepository):
    """Платежи в PostgreSQL.

    Каждый метод — ровно один SQL-запрос.
    """

    def __init__(self, session: AsyncSession, mapper: PaymentMapper | None = None) -> None:
        """:param session: сессия текущего Unit of Work."""
        self._session = session
        self._mapper = mapper or PaymentMapper()
        self._table = PaymentModel.__table__

    async def add_if_absent(self, payment: Payment) -> bool:
        """``INSERT … ON CONFLICT (idempotency_key) DO NOTHING RETURNING id``.

        Конкурентная вставка того же ключа ждёт фиксации первой
        транзакции на уникальном индексе и получает пустой RETURNING.
        """
        statement = (
            insert(self._table)
            .values(self._mapper.to_insert_values(payment))
            .on_conflict_do_nothing(index_elements=[self._table.c.idempotency_key])
            .returning(self._table.c.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def get_by_idempotency_key(self, key: IdempotencyKey) -> Payment | None:
        """Поиск по уникальному индексу ключа."""
        row = await self._session.scalar(select(PaymentModel).where(PaymentModel.idempotency_key == key.value))
        return self._mapper.to_domain(row) if row else None

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        """``SELECT … FOR UPDATE`` по первичному ключу."""
        row = await self._session.scalar(select(PaymentModel).where(PaymentModel.id == payment_id).with_for_update())
        return self._mapper.to_domain(row) if row else None

    async def update(self, payment: Payment) -> None:
        """``UPDATE`` изменяемых полей по первичному ключу."""
        await self._session.execute(
            update(self._table).where(self._table.c.id == payment.id).values(self._mapper.to_mutable_values(payment))
        )
