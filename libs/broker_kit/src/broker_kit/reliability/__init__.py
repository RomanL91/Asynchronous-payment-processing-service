"""Надёжная обработка входящих сообщений.

Обработка сообщения проходит через ``ReliableMessageExecutor``:

1. Обработчик выполнился успешно — ``ack``.
2. Упал — ``FailurePolicy`` (цепочка правил, Chain of Responsibility)
   выбирает действие (Strategy):

   * ``DeadLetterAction`` — ошибка постоянная или попытки исчерпаны:
     ``reject(requeue=False)``, брокер сам перекладывает сообщение
     через DLX в ``<queue>.dlq``;
   * ``RetryLaterAction`` — ошибка временная: копия публикуется в
     ``<queue>.retry.N`` с увеличенным ``x-attempt``, оригинал ``ack``.

Порядок «сначала опубликовать копию, потом ack» даёт at-least-once:
при падении между шагами сообщение придёт дважды, но не потеряется.
Дубликаты отсекают идемпотентные обработчики сервисов.
"""

from broker_kit.reliability.attempts import DeliveryAttempt
from broker_kit.reliability.backoff import BackoffSchedule, ExponentialBackoff
from broker_kit.reliability.classifier import ErrorClassifier, TypeBasedErrorClassifier
from broker_kit.reliability.errors import PermanentError, TransientError
from broker_kit.reliability.executor import ReliableMessageExecutor
from broker_kit.reliability.message import InboundMessage, MessageHandler
from broker_kit.reliability.policy import FailurePolicy
from broker_kit.reliability.publisher import RetryPublisher
from broker_kit.reliability.subscription import ReliableSubscription

__all__ = [
    "BackoffSchedule",
    "DeliveryAttempt",
    "ErrorClassifier",
    "ExponentialBackoff",
    "FailurePolicy",
    "InboundMessage",
    "MessageHandler",
    "PermanentError",
    "ReliableMessageExecutor",
    "ReliableSubscription",
    "RetryPublisher",
    "TransientError",
    "TypeBasedErrorClassifier",
]
