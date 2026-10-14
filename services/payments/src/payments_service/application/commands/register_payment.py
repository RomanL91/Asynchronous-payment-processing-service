"""Команда регистрации платежа с защитой от дублей."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from payments_service.application.exceptions import IdempotencyConflictError
from payments_service.application.fingerprint import RequestFingerprintCalculator
from payments_service.application.integration import OutboxMessageMapper
from payments_service.application.ports import Clock, IdGenerator, UnitOfWorkFactory
from payments_service.application.read_models import PaymentAcceptance
from payments_service.domain import Currency, IdempotencyKey, Money, Payment, RequestFingerprint


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterPaymentCommand:
    """Запрос клиента на создание платежа."""

    idempotency_key: str
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    webhook_url: str


class IdempotentReplayGuard:
    """Решает судьбу запроса с уже занятым ключом идемпотентности.

    * то же тело — честный повтор: возвращаем существующий платёж;
    * другое тело — ошибка клиента: ``409 Conflict``.
    """

    def resolve(self, existing: Payment, fingerprint: RequestFingerprint) -> PaymentAcceptance:
        """Возвращает ответ для повтора или бросает конфликт.

        :raises IdempotencyConflictError: ключ использован с другим телом.
        """
        if existing.fingerprint != fingerprint:
            raise IdempotencyConflictError(str(existing.idempotency_key))
        return PaymentAcceptance.of(existing, replayed=True)


class RegisterPaymentHandler:
    """Создаёт платёж и событие ``payment.created`` в одной транзакции.

    Идемпотентность обеспечивает уникальный индекс по ключу и вставка
    ``INSERT … ON CONFLICT DO NOTHING``: при гонке двух одинаковых
    запросов второй дождётся фиксации первого, не вставит строку и пойдёт
    по ветке повтора. Исключения как механизм управления потоком не нужны.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        fingerprints: RequestFingerprintCalculator,
        outbox_mapper: OutboxMessageMapper,
        replay_guard: IdempotentReplayGuard,
    ) -> None:
        """Сохраняет зависимости."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._fingerprints = fingerprints
        self._outbox_mapper = outbox_mapper
        self._replay_guard = replay_guard

    async def handle(self, command: RegisterPaymentCommand) -> PaymentAcceptance:
        """Регистрирует платёж или возвращает ранее созданный.

        :param command: параметры платежа.
        :return: идентификатор, статус, дата создания и признак повтора.
        :raises IdempotencyConflictError: ключ занят запросом с другим телом.
        """
        key = IdempotencyKey(command.idempotency_key)
        money = Money(command.amount, command.currency)
        fingerprint = self._fingerprints.calculate(
            money=money,
            description=command.description,
            metadata=command.metadata,
            webhook_url=command.webhook_url,
        )
        payment = Payment.register(
            payment_id=self._ids.new_id(),
            idempotency_key=key,
            fingerprint=fingerprint,
            money=money,
            description=command.description,
            metadata=command.metadata,
            webhook_url=command.webhook_url,
            now=self._clock.now(),
        )

        async with self._uow_factory() as uow:
            if await uow.payments.add_if_absent(payment):
                await uow.outbox.add_many(self._outbox_mapper.to_outbox(payment.pull_events()))
                await uow.commit()
                return PaymentAcceptance.of(payment, replayed=False)
            existing = await uow.payments.get_by_idempotency_key(key)

        if existing is None:  # pragma: no cover — строки не удаляются
            raise RuntimeError(f"Ключ {key} занят, но платёж не найден")
        return self._replay_guard.resolve(existing, fingerprint)
