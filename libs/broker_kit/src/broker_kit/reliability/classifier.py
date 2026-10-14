"""Классификация ошибок на временные и постоянные (Strategy)."""

import json
from abc import ABC, abstractmethod

from pydantic import ValidationError

from broker_kit.reliability.errors import PermanentError, TransientError


class ErrorClassifier(ABC):
    """Стратегия: стоит ли повторять обработку после ошибки."""

    @abstractmethod
    def is_retryable(self, error: BaseException) -> bool:
        """Определяет, имеет ли смысл повтор.

        :param error: исключение обработчика.
        :return: ``True`` — повторять, ``False`` — сразу в DLQ.
        """


class TypeBasedErrorClassifier(ErrorClassifier):
    """Классификация по типу исключения.

    Порядок проверки:

    1. ``TransientError`` — всегда повторяем;
    2. ``PermanentError``, ошибки разбора тела и типы, переданные
       сервисом, — не повторяем («ядовитые» сообщения);
    3. всё остальное (например, недоступность БД) — повторяем:
       неизвестная ошибка скорее инфраструктурная и временная.
    """

    _ALWAYS_PERMANENT: tuple[type[BaseException], ...] = (
        PermanentError,
        ValidationError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    )

    def __init__(self, permanent: tuple[type[BaseException], ...] = ()) -> None:
        """Сохраняет дополнительные постоянные типы ошибок сервиса.

        :param permanent: доменные/прикладные исключения, повтор которых бессмыслен.
        """
        self._permanent = self._ALWAYS_PERMANENT + permanent

    def is_retryable(self, error: BaseException) -> bool:
        """Определяет, имеет ли смысл повтор."""
        if isinstance(error, TransientError):
            return True
        return not isinstance(error, self._permanent)
