"""Тесты доменной модели платежа."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from payments_service.domain import (
    Currency,
    IdempotencyKey,
    InvalidIdempotencyKeyError,
    InvalidMoneyError,
    Money,
    OutcomeResolution,
    Payment,
    PaymentRegistered,
    PaymentStatus,
    RequestFingerprint,
)
from payments_service.infrastructure.system import UuidV7Generator

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _payment() -> Payment:
    return Payment.register(
        payment_id=uuid4(),
        idempotency_key=IdempotencyKey("k-1"),
        fingerprint=RequestFingerprint("a" * 64),
        money=Money(Decimal("10.50"), Currency.USD),
        description="тест",
        metadata={},
        webhook_url="https://example.com/hook",
        now=NOW,
    )


class TestMoney:
    """Инварианты суммы."""

    @pytest.mark.parametrize("amount", ["0", "-1", "1.001", "1e17", "NaN"])
    def test_rejects_invalid_amount(self, amount: str) -> None:
        """Неположительные, сверхточные, огромные и NaN суммы запрещены."""
        with pytest.raises(InvalidMoneyError):
            Money(Decimal(amount), Currency.RUB)

    @pytest.mark.parametrize(("amount", "normalized"), [("100", "100.00"), ("1.5", "1.50"), ("1.500", "1.50")])
    def test_normalizes_amount(self, amount: str, normalized: str) -> None:
        """Разные записи одной суммы канонизируются одинаково."""
        assert Money(Decimal(amount), Currency.RUB).normalized_amount() == normalized


class TestIdempotencyKey:
    """Формат ключа идемпотентности."""

    @pytest.mark.parametrize("value", ["", "с пробелом", "кириллица", "x" * 256])
    def test_rejects_invalid(self, value: str) -> None:
        """Пустые, с пробелами, не-ASCII и длинные ключи запрещены."""
        with pytest.raises(InvalidIdempotencyKeyError):
            IdempotencyKey(value)


class TestPaymentLifecycle:
    """Конечный автомат статусов."""

    def test_register_creates_pending_payment_with_event(self) -> None:
        """Новый платёж — pending и одно событие регистрации."""
        payment = _payment()
        events = payment.pull_events()
        assert payment.status is PaymentStatus.PENDING
        assert [type(e) for e in events] == [PaymentRegistered]
        assert payment.pull_events() == []

    def test_first_outcome_wins(self) -> None:
        """Первый результат применяется, повтор и противоречие — нет."""
        payment = _payment()
        assert payment.apply_outcome(PaymentStatus.SUCCEEDED, NOW) is OutcomeResolution.APPLIED
        assert payment.apply_outcome(PaymentStatus.SUCCEEDED, NOW) is OutcomeResolution.DUPLICATE
        assert payment.apply_outcome(PaymentStatus.FAILED, NOW) is OutcomeResolution.CONFLICT
        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.processed_at == NOW

    def test_pending_is_not_a_valid_outcome(self) -> None:
        """Результат обработки не может быть pending."""
        with pytest.raises(ValueError):
            _payment().apply_outcome(PaymentStatus.PENDING, NOW)

    def test_webhook_awaited_only_for_final_status_once(self) -> None:
        """Webhook ждут только окончательные платежи и только до отметки."""
        payment = _payment()
        assert not payment.awaits_webhook
        payment.apply_outcome(PaymentStatus.FAILED, NOW)
        assert payment.awaits_webhook
        assert payment.mark_webhook_delivered(NOW) is True
        assert payment.mark_webhook_delivered(NOW) is False
        assert not payment.awaits_webhook


def test_uuid7_is_time_ordered_and_versioned() -> None:
    """UUIDv7 монотонны во времени (между миллисекундами) и имеют версию 7."""
    generator = UuidV7Generator()
    first = generator.new_id()
    import time

    time.sleep(0.002)
    second = generator.new_id()
    assert first.version == 7 and second.version == 7
    assert first < second
