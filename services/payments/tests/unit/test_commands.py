"""Тесты команд: регистрация (идемпотентность) и применение результата."""

import asyncio
from uuid import uuid4

import pytest

from payments_service.application.commands import (
    ApplyProcessingResultCommand,
    ApplyProcessingResultHandler,
    RegisterPaymentHandler,
)
from payments_service.application.exceptions import IdempotencyConflictError, PaymentNotFoundError
from payments_service.application.ports import WebhookTemporarilyUnavailableError
from payments_service.domain import OutcomeResolution, PaymentStatus
from tests.conftest import make_command
from tests.fakes import FixedClock, InMemoryStore, RecordingWebhookSender


class TestRegisterPayment:
    """Регистрация платежа и защита от дублей."""

    async def test_creates_payment_and_outbox_message_atomically(
        self, register_handler: RegisterPaymentHandler, store: InMemoryStore
    ) -> None:
        """Платёж и событие payment.created.v1 фиксируются одним commit."""
        acceptance = await register_handler.handle(make_command())

        assert acceptance.replayed is False
        assert acceptance.status is PaymentStatus.PENDING
        assert store.commits == 1
        [message] = store.outbox.values()
        assert message.event_type == "payment.created.v1"
        assert message.payload["payment_id"] == str(acceptance.payment_id)
        assert message.payload["amount"] == "1500.00"

    async def test_same_key_and_body_returns_same_payment(
        self, register_handler: RegisterPaymentHandler, store: InMemoryStore
    ) -> None:
        """Повтор — тот же payment_id, без нового платежа и события."""
        first = await register_handler.handle(make_command())
        second = await register_handler.handle(make_command(amount="1500"))  # та же сумма в другой записи

        assert second.payment_id == first.payment_id
        assert second.replayed is True
        assert len(store.payments) == 1
        assert len(store.outbox) == 1

    async def test_same_key_different_body_conflicts(self, register_handler: RegisterPaymentHandler) -> None:
        """Тот же ключ с другим телом — конфликт."""
        await register_handler.handle(make_command())
        with pytest.raises(IdempotencyConflictError):
            await register_handler.handle(make_command(amount="99.99"))

    async def test_concurrent_duplicates_create_one_payment(
        self, register_handler: RegisterPaymentHandler, store: InMemoryStore
    ) -> None:
        """Десять конкурентных одинаковых запросов — один платёж."""
        results = await asyncio.gather(*(register_handler.handle(make_command()) for _ in range(10)))
        assert len({r.payment_id for r in results}) == 1
        assert len(store.payments) == 1


class TestApplyProcessingResult:
    """Применение результата и доставка webhook."""

    async def _register(self, register_handler: RegisterPaymentHandler) -> ApplyProcessingResultCommand:
        acceptance = await register_handler.handle(make_command())
        return ApplyProcessingResultCommand(
            payment_id=acceptance.payment_id,
            outcome=PaymentStatus.SUCCEEDED,
            processed_at=acceptance.created_at,
        )

    async def test_applies_result_and_sends_single_webhook(
        self,
        register_handler: RegisterPaymentHandler,
        apply_handler: ApplyProcessingResultHandler,
        store: InMemoryStore,
        webhook_sender: RecordingWebhookSender,
    ) -> None:
        """Первый результат применяется; дубль не шлёт второй webhook."""
        command = await self._register(register_handler)

        assert await apply_handler.handle(command) is OutcomeResolution.APPLIED
        assert await apply_handler.handle(command) is OutcomeResolution.DUPLICATE

        payment = store.payments[command.payment_id]
        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.webhook_delivered_at is not None
        assert [n.status for n in webhook_sender.sent] == ["succeeded"]

    async def test_conflicting_duplicate_keeps_first_result(
        self,
        register_handler: RegisterPaymentHandler,
        apply_handler: ApplyProcessingResultHandler,
        store: InMemoryStore,
    ) -> None:
        """Противоречащий результат игнорируется — побеждает первый."""
        command = await self._register(register_handler)
        await apply_handler.handle(command)

        conflicting = ApplyProcessingResultCommand(
            payment_id=command.payment_id, outcome=PaymentStatus.FAILED, processed_at=command.processed_at
        )
        assert await apply_handler.handle(conflicting) is OutcomeResolution.CONFLICT
        assert store.payments[command.payment_id].status is PaymentStatus.SUCCEEDED

    async def test_webhook_failure_keeps_status_and_retry_delivers(
        self,
        register_handler: RegisterPaymentHandler,
        apply_handler: ApplyProcessingResultHandler,
        store: InMemoryStore,
        webhook_sender: RecordingWebhookSender,
        clock: FixedClock,
    ) -> None:
        """Сбой webhook не откатывает статус; ретрай сообщения доотправляет уведомление."""
        command = await self._register(register_handler)
        webhook_sender.error = WebhookTemporarilyUnavailableError("503")

        with pytest.raises(WebhookTemporarilyUnavailableError):
            await apply_handler.handle(command)
        assert store.payments[command.payment_id].status is PaymentStatus.SUCCEEDED
        assert store.payments[command.payment_id].webhook_delivered_at is None

        webhook_sender.error = None
        clock.advance(1)
        assert await apply_handler.handle(command) is OutcomeResolution.DUPLICATE
        assert store.payments[command.payment_id].webhook_delivered_at == clock.now()
        assert len(webhook_sender.sent) == 1

    async def test_unknown_payment_is_permanent_error(self, apply_handler: ApplyProcessingResultHandler) -> None:
        """Неизвестный платёж — PaymentNotFoundError."""
        command = ApplyProcessingResultCommand(
            payment_id=uuid4(), outcome=PaymentStatus.FAILED, processed_at=FixedClock().now()
        )
        with pytest.raises(PaymentNotFoundError):
            await apply_handler.handle(command)
