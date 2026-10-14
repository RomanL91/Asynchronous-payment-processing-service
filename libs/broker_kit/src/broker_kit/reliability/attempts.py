"""Номер попытки доставки как value object."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from broker_kit.contracts.headers import MessageHeaders


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """Номер текущей попытки обработки сообщения (с единицы).

    Счётчик хранится в заголовке ``x-attempt``. Штатный ``x-death`` не
    используется: при ретрае через повторную публикацию он не отражает
    число наших попыток однозначно.
    """

    number: int

    def __post_init__(self) -> None:
        """Проверяет инвариант: номер попытки положителен."""
        if self.number < 1:
            raise ValueError("Номер попытки должен быть >= 1")

    @classmethod
    def first(cls) -> Self:
        """Первая попытка."""
        return cls(1)

    @classmethod
    def from_headers(cls, headers: Mapping[str, Any] | None) -> Self:
        """Восстанавливает номер попытки из заголовков.

        Некорректное значение трактуется как первая попытка: битый
        служебный заголовок не должен превращать сообщение в «ядовитое».

        :param headers: заголовки сообщения.
        :return: номер попытки.
        """
        raw = (headers or {}).get(MessageHeaders.ATTEMPT)
        try:
            return cls(max(int(raw), 1)) if raw is not None else cls.first()
        except (TypeError, ValueError):
            return cls.first()

    def next(self) -> Self:
        """Следующая попытка."""
        return type(self)(self.number + 1)

    def as_header(self) -> dict[str, int]:
        """Заголовок для повторной публикации."""
        return {MessageHeaders.ATTEMPT: self.number}
