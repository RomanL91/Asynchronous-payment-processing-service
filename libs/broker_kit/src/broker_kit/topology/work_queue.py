"""Описание рабочей очереди с отложенными ретраями и DLQ.

Схема для очереди ``Q`` с маршрутом ``rk`` в обменнике ``EX``::

    EX --rk--> Q ----------------------------> потребитель
               |  x-dead-letter-exchange = DLX
               |  x-dead-letter-routing-key = Q
               v
    (reject) DLX --Q--> Q.dlq                 окончательно упавшие

    потребитель --публикация--> Q.retry.N     (default exchange)
                                  | x-message-ttl = delay_N
                                  | x-dead-letter-exchange = EX
                                  | x-dead-letter-routing-key = rk
                                  v
                                 EX --rk--> Q снова

Почему на каждую задержку своя очередь, а не per-message TTL:
RabbitMQ истекает сообщения только с головы очереди, поэтому сообщение
с TTL 4 с, оказавшееся перед сообщением с TTL 1 с, задержит второе
(head-of-line blocking). В очереди с единым TTL такого не бывает.
"""

from dataclasses import dataclass
from typing import Any

from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue


@dataclass(frozen=True, slots=True)
class WorkQueueTopology:
    """Неизменяемое описание рабочей очереди и её вспомогательных очередей.

    :ivar queue_name: имя основной очереди.
    :ivar routing_key: ключ маршрутизации в основном обменнике.
    :ivar exchange_name: основной обменник (direct).
    :ivar dead_letter_exchange_name: обменник для DLQ (direct).
    :ivar retry_delays_ms: задержки перед повторными попытками;
        длина кортежа = ``max_attempts - 1``.
    """

    queue_name: str
    routing_key: str
    exchange_name: str
    dead_letter_exchange_name: str
    retry_delays_ms: tuple[int, ...]

    @property
    def max_attempts(self) -> int:
        """Общее число попыток обработки, включая первую."""
        return len(self.retry_delays_ms) + 1

    @property
    def dead_letter_queue_name(self) -> str:
        """Имя очереди окончательно необработанных сообщений."""
        return f"{self.queue_name}.dlq"

    def retry_queue_name(self, level: int) -> str:
        """Имя retry-очереди заданного уровня.

        :param level: уровень с единицы; уровень N ждёт ``retry_delays_ms[N-1]``.
        :return: имя очереди.
        """
        return f"{self.queue_name}.retry.{level}"

    def exchange(self) -> RabbitExchange:
        """Основной durable direct-обменник."""
        return RabbitExchange(self.exchange_name, type=ExchangeType.DIRECT, durable=True)

    def dead_letter_exchange(self) -> RabbitExchange:
        """Durable direct-обменник для мёртвых писем."""
        return RabbitExchange(self.dead_letter_exchange_name, type=ExchangeType.DIRECT, durable=True)

    def main_queue(self) -> RabbitQueue:
        """Основная очередь; отклонённые сообщения уходят в DLX."""
        return RabbitQueue(
            self.queue_name,
            durable=True,
            routing_key=self.routing_key,
            arguments=self._dead_letter_arguments(),
        )

    def dead_letter_queue(self) -> RabbitQueue:
        """Очередь мёртвых писем, привязана к DLX по имени основной очереди."""
        return RabbitQueue(self.dead_letter_queue_name, durable=True, routing_key=self.queue_name)

    def retry_queues(self) -> tuple[RabbitQueue, ...]:
        """Все retry-очереди по возрастанию задержки."""
        return tuple(self._retry_queue(level) for level in range(1, self.max_attempts))

    def retry_queue_after(self, failed_attempt: int) -> RabbitQueue:
        """Retry-очередь, в которую отправляется сообщение после неудачи.

        :param failed_attempt: номер неудавшейся попытки (с единицы).
        :return: очередь, ожидающая ``retry_delays_ms[failed_attempt - 1]``.
        :raises ValueError: если попытки исчерпаны.
        """
        if not 1 <= failed_attempt < self.max_attempts:
            raise ValueError(f"Нет retry-очереди после попытки {failed_attempt} из {self.max_attempts}")
        return self._retry_queue(failed_attempt)

    def _retry_queue(self, level: int) -> RabbitQueue:
        """Строит retry-очередь уровня ``level``."""
        return RabbitQueue(
            self.retry_queue_name(level),
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delays_ms[level - 1],
                "x-dead-letter-exchange": self.exchange_name,
                "x-dead-letter-routing-key": self.routing_key,
            },
        )

    def _dead_letter_arguments(self) -> dict[str, Any]:
        """Аргументы основной очереди, включающие нативный DLX."""
        return {
            "x-dead-letter-exchange": self.dead_letter_exchange_name,
            "x-dead-letter-routing-key": self.queue_name,
        }
