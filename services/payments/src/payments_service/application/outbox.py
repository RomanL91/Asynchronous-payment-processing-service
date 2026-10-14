"""Сообщение transactional outbox."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxMessage:
    """Интеграционное событие, ожидающее публикации в брокер.

    Записывается в ту же транзакцию, что и изменение агрегата: либо
    сохраняются оба, либо ни одно. Публикацию выполняет relay.

    :ivar id: идентификатор; становится AMQP ``message_id``.
    :ivar aggregate_id: идентификатор платежа — для диагностики.
    :ivar event_type: тип интеграционного события (ключ маршрутизации relay).
    :ivar payload: JSON-тело события.
    :ivar created_at: момент записи.
    """

    id: UUID
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
