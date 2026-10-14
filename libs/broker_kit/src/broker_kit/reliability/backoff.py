"""Расписания задержек между повторными попытками (Strategy)."""

from abc import ABC, abstractmethod


class BackoffSchedule(ABC):
    """Стратегия вычисления задержек.

    Задержки статичны и материализуются в TTL retry-очередей,
    поэтому стратегия возвращает весь набор сразу.
    """

    @property
    @abstractmethod
    def max_attempts(self) -> int:
        """Общее число попыток, включая первую."""

    @abstractmethod
    def delays_ms(self) -> tuple[int, ...]:
        """Задержки перед попытками 2..max_attempts, в миллисекундах."""


class ExponentialBackoff(BackoffSchedule):
    """Экспоненциальная задержка: ``base * multiplier ** (n - 1)``.

    При ``base=1000, multiplier=2, max_attempts=3`` получаем 1 с и 2 с.
    """

    def __init__(self, base_delay_ms: int, multiplier: float, max_attempts: int) -> None:
        """Проверяет и сохраняет параметры.

        :param base_delay_ms: задержка перед второй попыткой.
        :param multiplier: множитель роста задержки.
        :param max_attempts: общее число попыток.
        """
        if base_delay_ms < 1 or multiplier < 1 or max_attempts < 1:
            raise ValueError("Некорректные параметры экспоненциальной задержки")
        self._base_delay_ms = base_delay_ms
        self._multiplier = multiplier
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """Общее число попыток, включая первую."""
        return self._max_attempts

    def delays_ms(self) -> tuple[int, ...]:
        """Задержки перед попытками 2..max_attempts."""
        return tuple(round(self._base_delay_ms * self._multiplier**step) for step in range(self._max_attempts - 1))
