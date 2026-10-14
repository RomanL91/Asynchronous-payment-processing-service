"""Системные порты: время и идентификаторы.

Вынесены за абстракции, чтобы сценарии были детерминированы в тестах.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


class Clock(ABC):
    """Источник текущего времени."""

    @abstractmethod
    def now(self) -> datetime:
        """Текущий момент (timezone-aware, UTC)."""


class IdGenerator(ABC):
    """Генератор идентификаторов сущностей."""

    @abstractmethod
    def new_id(self) -> UUID:
        """Новый уникальный идентификатор."""
