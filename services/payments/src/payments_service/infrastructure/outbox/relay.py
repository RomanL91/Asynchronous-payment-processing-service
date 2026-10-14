"""Relay: перенос записей outbox в брокер."""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from payments_service.application.outbox import OutboxMessage
from payments_service.application.ports import Clock, UnitOfWork, UnitOfWorkFactory
from payments_service.infrastructure.outbox.publisher import OutboxPublisher


@dataclass(slots=True)
class _BatchOutcome:
    """Итог публикации пачки."""

    published: list[UUID] = field(default_factory=list)
    failed: list[tuple[UUID, BaseException]] = field(default_factory=list)


class OutboxRelay:
    """Публикует одну пачку outbox за вызов.

    Пачка блокируется ``FOR UPDATE SKIP LOCKED`` на время транзакции,
    поэтому несколько экземпляров relay делят работу без пересечений.
    Сообщения пачки публикуются конкурентно: confirms на одном канале
    конвейеризуются, и пачка уходит за время ~одного round-trip, а не N.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        publisher: OutboxPublisher,
        clock: Clock,
        batch_size: int,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет зависимости."""
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._clock = clock
        self._batch_size = batch_size
        self._logger = logger or logging.getLogger(__name__)

    @property
    def batch_size(self) -> int:
        """Размер пачки."""
        return self._batch_size

    async def relay_once(self) -> int:
        """Публикует одну пачку.

        :return: число опубликованных сообщений.
        """
        async with self._uow_factory() as uow:
            batch = await uow.outbox.lock_pending_batch(self._batch_size)
            if not batch:
                return 0
            outcome = await self._publish(batch)
            await self._persist(uow, outcome)
            await uow.commit()
        self._report(outcome)
        return len(outcome.published)

    async def _publish(self, batch: Sequence[OutboxMessage]) -> _BatchOutcome:
        """Публикует пачку конкурентно и собирает результаты."""
        results = await asyncio.gather(*(self._publisher.publish(m) for m in batch), return_exceptions=True)
        outcome = _BatchOutcome()
        for message, result in zip(batch, results, strict=True):
            if isinstance(result, BaseException):
                outcome.failed.append((message.id, result))
            else:
                outcome.published.append(message.id)
        return outcome

    async def _persist(self, uow: UnitOfWork, outcome: _BatchOutcome) -> None:
        """Фиксирует опубликованные и неудачные сообщения."""
        await uow.outbox.mark_published(outcome.published, self._clock.now())
        for message_id, error in outcome.failed:
            await uow.outbox.register_failure(message_id, f"{type(error).__name__}: {error}")

    def _report(self, outcome: _BatchOutcome) -> None:
        """Логирует итог пачки."""
        if outcome.published:
            self._logger.info("Outbox: опубликовано %d", len(outcome.published))
        for message_id, error in outcome.failed:
            self._logger.warning("Outbox: сообщение %s не опубликовано: %r", message_id, error)


class OutboxRelayWorker:
    """Бесконечный цикл relay с корректной остановкой.

    * пачка заполнена целиком — сразу берём следующую (догоняем бэклог);
    * outbox пуст — ждём ``poll_interval`` **или** сигнала остановки,
      что ближе (``asyncio.wait_for`` на ``Event``), поэтому SIGTERM
      обрабатывается мгновенно, а не по окончании сна;
    * ошибка (например, БД недоступна) — логируем и ждём, процесс не падает.
    """

    def __init__(self, relay: OutboxRelay, poll_interval_s: float, logger: logging.Logger | None = None) -> None:
        """Сохраняет зависимости."""
        self._relay = relay
        self._poll_interval_s = poll_interval_s
        self._logger = logger or logging.getLogger(__name__)

    async def run(self, stop: asyncio.Event) -> None:
        """Крутит цикл до установки ``stop``."""
        self._logger.info(
            "Outbox relay запущен (пачка %d, опрос %.2f с)", self._relay.batch_size, self._poll_interval_s
        )
        while not stop.is_set():
            try:
                published = await self._relay.relay_once()
            except Exception:
                self._logger.exception("Outbox relay: ошибка итерации")
                published = 0
            if published < self._relay.batch_size:
                await self._sleep(stop)
        self._logger.info("Outbox relay остановлен")

    async def _sleep(self, stop: asyncio.Event) -> None:
        """Пауза, прерываемая сигналом остановки."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_s)
