"""Стратегии эмуляции: исход, задержка, сбои (паттерн Strategy).

Случайность вынесена в стратегии с внедряемым генератором, поэтому
сервис детерминированно тестируется подстановкой фиксированных стратегий.
"""

import asyncio
import random
from abc import ABC, abstractmethod

from gateway_mock.domain.charge import ChargeStatus


class OutcomeStrategy(ABC):
    """Определяет исход нового списания."""

    @abstractmethod
    def decide(self) -> ChargeStatus:
        """Возвращает ``succeeded`` или ``failed``."""


class RandomOutcomeStrategy(OutcomeStrategy):
    """Успех с заданной вероятностью."""

    def __init__(self, success_rate: float, rng: random.Random | None = None) -> None:
        """:param success_rate: доля успехов 0..1. :param rng: генератор случайных чисел."""
        self._success_rate = success_rate
        self._rng = rng or random.Random()

    def decide(self) -> ChargeStatus:
        """Бросок с вероятностью ``success_rate``."""
        return ChargeStatus.SUCCEEDED if self._rng.random() < self._success_rate else ChargeStatus.FAILED


class LatencyStrategy(ABC):
    """Имитирует время обработки."""

    @abstractmethod
    async def wait(self) -> None:
        """Неблокирующая пауза."""


class UniformLatencyStrategy(LatencyStrategy):
    """Равномерно распределённая задержка.

    ``asyncio.sleep`` отдаёт управление event loop: пока одно списание
    «думает», шлюз обслуживает другие запросы — никакой блокировки потока.
    """

    def __init__(self, min_s: float, max_s: float, rng: random.Random | None = None) -> None:
        """:param min_s: нижняя граница. :param max_s: верхняя граница."""
        self._min_s = min_s
        self._max_s = max_s
        self._rng = rng or random.Random()

    async def wait(self) -> None:
        """Ждёт случайное время из диапазона."""
        await asyncio.sleep(self._rng.uniform(self._min_s, self._max_s))


class GatewayOverloadedError(Exception):
    """Шлюз временно не может принять запрос (эмуляция 503)."""


class FaultInjector(ABC):
    """Внедряет временные сбои до начала обработки."""

    @abstractmethod
    def maybe_fail(self) -> None:
        """Бросает ``GatewayOverloadedError`` или ничего не делает."""


class ProbabilisticFaultInjector(FaultInjector):
    """Сбой с заданной вероятностью (0 — выключено)."""

    def __init__(self, failure_rate: float, rng: random.Random | None = None) -> None:
        """:param failure_rate: доля сбоев 0..1."""
        self._failure_rate = failure_rate
        self._rng = rng or random.Random()

    def maybe_fail(self) -> None:
        """Бросок с вероятностью ``failure_rate``."""
        if self._failure_rate and self._rng.random() < self._failure_rate:
            raise GatewayOverloadedError("Шлюз перегружен, повторите позже")
