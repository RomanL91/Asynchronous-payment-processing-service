"""Интеграционные события сервисов процессинга.

Модели следуют принципу *tolerant reader*: неизвестные поля игнорируются
(``extra="ignore"``), поэтому производитель может добавлять поля, не
ломая уже развёрнутых потребителей.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IntegrationEvent(BaseModel):
    """Базовый класс интеграционного события.

    Каждое событие знает свой ``event_type`` — стабильный идентификатор
    типа, который передаётся в заголовке и используется для маршрутизации
    из outbox.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_type: ClassVar[str]

    def to_json_bytes(self) -> bytes:
        """Сериализует событие в JSON для тела AMQP-сообщения.

        :return: UTF-8 байты JSON.
        """
        return self.model_dump_json().encode()


class PaymentCreatedV1(IntegrationEvent):
    """Платёж зарегистрирован и ожидает обработки.

    Событие несёт всё, что нужно процессору (паттерн *event-carried state
    transfer*): процессор не имеет доступа к БД payments-service.
    """

    event_type: ClassVar[str] = "payment.created.v1"

    payment_id: UUID
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str
    created_at: datetime


class ProcessingStatus(StrEnum):
    """Итог обработки платежа шлюзом."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PaymentProcessedV1(IntegrationEvent):
    """Шлюз вернул окончательный результат по платежу."""

    event_type: ClassVar[str] = "payment.processed.v1"

    payment_id: UUID
    status: ProcessingStatus
    gateway_charge_id: str
    processed_at: datetime
