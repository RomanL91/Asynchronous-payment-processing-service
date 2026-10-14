"""Репозиторий transactional outbox."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payments_service.application.outbox import OutboxMessage
from payments_service.application.ports import OutboxRepository
from payments_service.infrastructure.db.mappers import OutboxMapper
from payments_service.infrastructure.db.models import OutboxModel


class SqlAlchemyOutboxRepository(OutboxRepository):
    """Outbox в PostgreSQL; все операции пакетные."""

    def __init__(self, session: AsyncSession, mapper: OutboxMapper | None = None) -> None:
        """:param session: сессия текущего Unit of Work."""
        self._session = session
        self._mapper = mapper or OutboxMapper()
        self._table = OutboxModel.__table__

    async def add_many(self, messages: Sequence[OutboxMessage]) -> None:
        """Один multi-row ``INSERT`` на все сообщения."""
        if not messages:
            return
        await self._session.execute(insert(self._table), [self._mapper.to_insert_values(m) for m in messages])

    async def lock_pending_batch(self, limit: int) -> list[OutboxMessage]:
        """``SELECT … WHERE published_at IS NULL ORDER BY created_at LIMIT n FOR UPDATE SKIP LOCKED``.

        Условие и сортировка совпадают с частичным индексом ``ix_outbox_pending``.
        """
        rows = await self._session.scalars(
            select(OutboxModel)
            .where(OutboxModel.published_at.is_(None))
            .order_by(OutboxModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [self._mapper.to_domain(row) for row in rows]

    async def mark_published(self, message_ids: Sequence[UUID], at: datetime) -> None:
        """Один ``UPDATE … WHERE id IN (…)`` на всю пачку."""
        if not message_ids:
            return
        await self._session.execute(
            update(self._table).where(self._table.c.id.in_(message_ids)).values(published_at=at)
        )

    async def register_failure(self, message_id: UUID, error: str) -> None:
        """Атомарный инкремент счётчика попыток."""
        await self._session.execute(
            update(self._table)
            .where(self._table.c.id == message_id)
            .values(publish_attempts=self._table.c.publish_attempts + 1, last_error=error[:2000])
        )
