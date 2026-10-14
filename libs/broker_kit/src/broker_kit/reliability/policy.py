"""Политика реакции на ошибку: цепочка правил (Chain of Responsibility)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from broker_kit.reliability.actions import DeadLetterAction, FailureAction, RetryLaterAction
from broker_kit.reliability.attempts import DeliveryAttempt
from broker_kit.reliability.classifier import ErrorClassifier
from broker_kit.reliability.publisher import RetryPublisher
from broker_kit.topology.work_queue import WorkQueueTopology


@dataclass(frozen=True, slots=True)
class FailureContext:
    """Всё, что известно о неудачной попытке.

    :ivar error: исключение обработчика.
    :ivar attempt: номер неудавшейся попытки.
    :ivar topology: рабочая очередь, из которой пришло сообщение.
    """

    error: BaseException
    attempt: DeliveryAttempt
    topology: WorkQueueTopology


class FailureRule(ABC):
    """Звено цепочки: либо выбирает действие, либо передаёт дальше."""

    @abstractmethod
    def evaluate(self, context: FailureContext) -> FailureAction | None:
        """Возвращает действие или ``None``, если правило не применимо."""


class PermanentErrorRule(FailureRule):
    """Постоянная ошибка — сразу в DLQ, попытки не тратятся."""

    def __init__(self, classifier: ErrorClassifier) -> None:
        """:param classifier: стратегия классификации ошибок."""
        self._classifier = classifier

    def evaluate(self, context: FailureContext) -> FailureAction | None:
        """Срабатывает, если повтор бессмыслен."""
        if self._classifier.is_retryable(context.error):
            return None
        return DeadLetterAction(reason=f"постоянная ошибка {type(context.error).__name__}")


class AttemptsExhaustedRule(FailureRule):
    """Попытки исчерпаны — в DLQ."""

    def evaluate(self, context: FailureContext) -> FailureAction | None:
        """Срабатывает на последней попытке."""
        if context.attempt.number < context.topology.max_attempts:
            return None
        return DeadLetterAction(reason=f"исчерпано {context.topology.max_attempts} попыток")


class RetryLaterRule(FailureRule):
    """Терминальное правило: отложенный повтор."""

    def __init__(self, publisher: RetryPublisher) -> None:
        """:param publisher: публикатор копий в retry-очереди."""
        self._publisher = publisher

    def evaluate(self, context: FailureContext) -> FailureAction | None:
        """Всегда возвращает повтор в очередь с задержкой текущего уровня."""
        return RetryLaterAction(
            publisher=self._publisher,
            queue=context.topology.retry_queue_after(context.attempt.number),
            next_attempt=context.attempt.next(),
            error=context.error,
        )


class FailurePolicy:
    """Перебирает правила по порядку и возвращает первое действие."""

    def __init__(self, rules: Sequence[FailureRule]) -> None:
        """:param rules: правила в порядке приоритета; последнее должно быть терминальным."""
        if not rules:
            raise ValueError("Политика ошибок должна содержать хотя бы одно правило")
        self._rules = tuple(rules)

    @classmethod
    def default(cls, classifier: ErrorClassifier, publisher: RetryPublisher) -> Self:
        """Стандартная цепочка: постоянная ошибка → исчерпание → повтор."""
        return cls((PermanentErrorRule(classifier), AttemptsExhaustedRule(), RetryLaterRule(publisher)))

    def resolve(self, context: FailureContext) -> FailureAction:
        """Выбирает действие для упавшего сообщения.

        :param context: сведения о неудаче.
        :return: действие первого сработавшего правила.
        :raises LookupError: если цепочка не завершилась терминальным правилом.
        """
        for rule in self._rules:
            action = rule.evaluate(context)
            if action is not None:
                return action
        raise LookupError("Ни одно правило политики ошибок не сработало")
