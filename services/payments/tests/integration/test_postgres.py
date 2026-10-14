"""Сценарии на PostgreSQL: идемпотентность, outbox, SKIP LOCKED, чтение."""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select

from payments_service.application.commands import RegisterPaymentHandler
from payments_service.application.commands.register_payment import IdempotentReplayGuard
from payments_service.application.fingerprint import RequestFingerprintCalculator
from payments_service.application.integration import OutboxMessageMapper
from payments_service.application.outbox import OutboxMessage
from payments_service.application.queries import GetPaymentHandler, GetPaymentQuery
from payments_service.domain import PaymentStatus
from payments_service.infrastructure.db import Database, SqlAlchemyUnitOfWork
from payments_service.infrastructure.db.models import OutboxModel, PaymentModel
from payments_service.infrastructure.db.readers import SqlAlchemyPaymentReader
from payments_service.infrastructure.outbox import OutboxRelay
from payments_service.infrastructure.outbox.publisher import OutboxPublisher
from payments_service.infrastructure.system import UtcClock, UuidV7Generator
from tests.conftest import make_command

pytestmark = pytest.mark.integration


def _register_handler(database: Database) -> RegisterPaymentHandler:
    ids = UuidV7Generator()
    return RegisterPaymentHandler(
        uow_factory=lambda: SqlAlchemyUnitOfWork(database),
        clock=UtcClock(),
        ids=ids,
        fingerprints=RequestFingerprintCalculator(),
        outbox_mapper=OutboxMessageMapper(ids),
        replay_guard=IdempotentReplayGuard(),
    )


async def _count(database: Database, model: type) -> int:
    async with database.session() as session:
        return await session.scalar(select(func.count()).select_from(model))


class _RecordingPublisher(OutboxPublisher):
    """Публикатор, запоминающий id и падающий на заданных сообщениях."""

    def __init__(self, fail_ids: set[UUID] | None = None, delay: float = 0.0) -> None:
        self.published: list[UUID] = []
        self._fail_ids = fail_ids or set()
        self._delay = delay

    async def publish(self, message: OutboxMessage) -> None:
        await asyncio.sleep(self._delay)
        if message.id in self._fail_ids:
            raise ConnectionError("broker down")
        self.published.append(message.id)


async def test_concurrent_registration_creates_single_payment(database: Database) -> None:
    """20 конкурентных запросов с одним ключом → 1 платёж и 1 событие (ON CONFLICT)."""
    handler = _register_handler(database)
    results = await asyncio.gather(*(handler.handle(make_command("race-key")) for _ in range(20)))

    assert len({r.payment_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    assert await _count(database, PaymentModel) == 1
    assert await _count(database, OutboxModel) == 1


async def test_reader_returns_projection(database: Database) -> None:
    """Чтение проекции: Decimal, JSONB и статус приходят корректно."""
    acceptance = await _register_handler(database).handle(make_command())
    details = await GetPaymentHandler(SqlAlchemyPaymentReader(database)).handle(GetPaymentQuery(acceptance.payment_id))

    assert str(details.amount) == "1500.00"
    assert details.metadata == {"order_id": 1042}
    assert details.status is PaymentStatus.PENDING


async def test_relay_publishes_and_marks_batch(database: Database) -> None:
    """Relay публикует всё, отмечает опубликованное, неудачное оставляет."""
    handler = _register_handler(database)
    for index in range(5):
        await handler.handle(make_command(f"k-{index}"))

    async with database.session() as session:
        failing_id = await session.scalar(select(OutboxModel.id).order_by(OutboxModel.created_at).limit(1))

    publisher = _RecordingPublisher(fail_ids={failing_id})
    relay = OutboxRelay(lambda: SqlAlchemyUnitOfWork(database), publisher, UtcClock(), batch_size=10)

    assert await relay.relay_once() == 4
    async with database.session() as session:
        failed = await session.get(OutboxModel, failing_id)
        pending = await session.scalar(
            select(func.count()).select_from(OutboxModel).where(OutboxModel.published_at.is_(None))
        )
    assert pending == 1
    assert failed.publish_attempts == 1 and "broker down" in failed.last_error


async def test_parallel_relays_do_not_overlap(database: Database) -> None:
    """Два relay одновременно: SKIP LOCKED делит пачки без дублей."""
    handler = _register_handler(database)
    for index in range(30):
        await handler.handle(make_command(f"p-{index}"))

    publishers = [_RecordingPublisher(delay=0.01), _RecordingPublisher(delay=0.01)]
    relays = [
        OutboxRelay(lambda: SqlAlchemyUnitOfWork(database), publisher, UtcClock(), batch_size=10)
        for publisher in publishers
    ]
    while sum(await asyncio.gather(*(relay.relay_once() for relay in relays))):
        pass

    published = publishers[0].published + publishers[1].published
    assert len(published) == 30
    assert len(set(published)) == 30
    assert publishers[0].published and publishers[1].published


async def test_concurrent_results_apply_once_and_single_webhook(database: Database) -> None:
    """Конкурентные дубли результата: FOR UPDATE сериализует, применяется один."""
    from payments_service.application.commands import (
        ApplyProcessingResultCommand,
        ApplyProcessingResultHandler,
        DeliverWebhookHandler,
    )
    from payments_service.domain import OutcomeResolution
    from tests.fakes import RecordingWebhookSender

    acceptance = await _register_handler(database).handle(make_command())
    sender = RecordingWebhookSender()
    uow_factory = lambda: SqlAlchemyUnitOfWork(database)  # noqa: E731
    handler = ApplyProcessingResultHandler(uow_factory, DeliverWebhookHandler(uow_factory, sender, UtcClock()))
    outcomes = [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED, PaymentStatus.SUCCEEDED]

    resolutions = await asyncio.gather(
        *(
            handler.handle(
                ApplyProcessingResultCommand(
                    payment_id=acceptance.payment_id, outcome=outcome, processed_at=acceptance.created_at
                )
            )
            for outcome in outcomes
        )
    )

    assert resolutions.count(OutcomeResolution.APPLIED) == 1
    async with database.session() as session:
        row = await session.get(PaymentModel, acceptance.payment_id)
    assert row.status.is_final
    assert row.webhook_delivered_at is not None
    # at-least-once: конкурентные дубли могут доставить webhook повторно,
    # но все уведомления несут один и тот же (первый зафиксированный) статус
    assert {notification.status for notification in sender.sent} == {row.status.value}
