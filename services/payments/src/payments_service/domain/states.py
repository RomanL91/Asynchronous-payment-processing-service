"""Конечный автомат статусов платежа (паттерн State).

::

    pending ──outcome──▶ succeeded | failed      (единственный переход)
    succeeded/failed ──любой outcome──▶ без изменений

Повторный результат по уже завершённому платежу — нормальная ситуация
at-least-once доставки, а не ошибка: состояние возвращает
``DUPLICATE`` или ``CONFLICT``, и вызывающий код просто фиксирует факт.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar

from payments_service.domain.value_objects import PaymentStatus

if TYPE_CHECKING:
    from payments_service.domain.payment import Payment


class OutcomeResolution(StrEnum):
    """Чем закончилась попытка применить результат обработки."""

    APPLIED = "applied"
    """Статус изменён — первый результат."""

    DUPLICATE = "duplicate"
    """Платёж уже в этом же статусе — дубль сообщения."""

    CONFLICT = "conflict"
    """Платёж уже в другом окончательном статусе — побеждает первый результат."""

    @property
    def changed_state(self) -> bool:
        """Нужно ли сохранять сущность."""
        return self is OutcomeResolution.APPLIED


class PaymentState(ABC):
    """Поведение платежа, зависящее от его статуса."""

    status: ClassVar[PaymentStatus]

    @abstractmethod
    def apply_outcome(self, payment: "Payment", outcome: PaymentStatus, at: datetime) -> OutcomeResolution:
        """Применяет результат обработки к платежу.

        :param payment: платёж в данном состоянии.
        :param outcome: окончательный статус, пришедший от процессора.
        :param at: момент обработки шлюзом.
        :return: как был разрешён результат.
        """


class PendingState(PaymentState):
    """Ожидает обработки: принимает первый окончательный результат."""

    status = PaymentStatus.PENDING

    def apply_outcome(self, payment: "Payment", outcome: PaymentStatus, at: datetime) -> OutcomeResolution:
        """Переводит платёж в окончательный статус."""
        if not outcome.is_final:
            raise ValueError("Результат обработки должен быть окончательным статусом")
        payment.status = outcome
        payment.processed_at = at
        return OutcomeResolution.APPLIED


class FinalState(PaymentState):
    """Окончательное состояние: изменения игнорируются."""

    def __init__(self, status: PaymentStatus) -> None:
        """:param status: окончательный статус."""
        self._status = status

    def apply_outcome(self, payment: "Payment", outcome: PaymentStatus, at: datetime) -> OutcomeResolution:
        """Ничего не меняет, классифицирует повтор."""
        return OutcomeResolution.DUPLICATE if outcome is self._status else OutcomeResolution.CONFLICT


class PaymentStateRegistry:
    """Сопоставление статуса и объекта состояния (Flyweight: состояния без данных)."""

    _STATES: ClassVar[MappingProxyType[PaymentStatus, PaymentState]] = MappingProxyType(
        {
            PaymentStatus.PENDING: PendingState(),
            PaymentStatus.SUCCEEDED: FinalState(PaymentStatus.SUCCEEDED),
            PaymentStatus.FAILED: FinalState(PaymentStatus.FAILED),
        }
    )

    @classmethod
    def for_status(cls, status: PaymentStatus) -> PaymentState:
        """Возвращает состояние для статуса."""
        return cls._STATES[status]
