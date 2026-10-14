"""Value objects платёжного домена."""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from payments_service.domain.exceptions import InvalidIdempotencyKeyError, InvalidMoneyError


class Currency(StrEnum):
    """Поддерживаемые валюты (ISO 4217)."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    """Статус платежа."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def is_final(self) -> bool:
        """Окончательный ли статус (дальнейшие переходы запрещены)."""
        return self is not PaymentStatus.PENDING


@dataclass(frozen=True, slots=True)
class Money:
    """Денежная сумма в конкретной валюте.

    Инварианты: сумма строго положительна, не более двух знаков после
    запятой и не более 16 знаков в целой части (соответствует
    ``NUMERIC(18, 2)`` в БД). Float не допускается — только ``Decimal``.
    """

    amount: Decimal
    currency: Currency

    _MAX_INTEGER_DIGITS: ClassVar[int] = 16
    _SCALE: ClassVar[Decimal] = Decimal("0.01")

    def __post_init__(self) -> None:
        """Проверяет инварианты и приводит сумму к масштабу 2 (``100`` → ``100.00``)."""
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise InvalidMoneyError("Сумма должна быть конечным Decimal")
        if self.amount <= 0:
            raise InvalidMoneyError("Сумма должна быть положительной")
        if self.amount.adjusted() + 1 > self._MAX_INTEGER_DIGITS:
            raise InvalidMoneyError("Сумма слишком велика")
        if self.amount.normalize().as_tuple().exponent < -2:  # type: ignore[operator]
            raise InvalidMoneyError("Сумма может иметь не более двух знаков после запятой")
        object.__setattr__(self, "amount", self.amount.quantize(self._SCALE))

    def normalized_amount(self) -> str:
        """Каноническое строковое представление суммы: ``100.00``."""
        return str(self.amount)


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Клиентский ключ защиты от повторного создания платежа."""

    value: str

    _MAX_LENGTH: ClassVar[int] = 255
    _PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"^[\x21-\x7E]+$")

    def __post_init__(self) -> None:
        """Ключ — непустая строка печатных ASCII-символов без пробелов."""
        if not 0 < len(self.value) <= self._MAX_LENGTH or not self._PATTERN.match(self.value):
            raise InvalidIdempotencyKeyError(
                f"Idempotency-Key должен содержать 1..{self._MAX_LENGTH} печатных ASCII-символов"
            )

    def __str__(self) -> str:
        """Строковое значение ключа."""
        return self.value


@dataclass(frozen=True, slots=True)
class RequestFingerprint:
    """Отпечаток (SHA-256) содержимого запроса на создание платежа.

    Позволяет отличить честный повтор (тот же ключ и то же тело) от
    ошибки клиента (тот же ключ, другое тело).
    """

    value: str

    def __post_init__(self) -> None:
        """Отпечаток — 64 шестнадцатеричных символа."""
        if not re.fullmatch(r"[0-9a-f]{64}", self.value):
            raise ValueError("Отпечаток должен быть hex SHA-256")
