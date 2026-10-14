"""Каталог топологии системы процессинга платежей."""

from typing import Final

from broker_kit.reliability.backoff import BackoffSchedule
from broker_kit.topology.work_queue import WorkQueueTopology


class PaymentsTopology:
    """Единственный источник правды об именах обменников и очередей.

    Поток сообщений::

        payments-service --payment.new-------> payments.new       --> processor
        processor        --payment.processed-> payments.processed --> payments-service
    """

    EXCHANGE: Final[str] = "payments"
    DEAD_LETTER_EXCHANGE: Final[str] = "payments.dlx"

    NEW_QUEUE: Final[str] = "payments.new"
    NEW_ROUTING_KEY: Final[str] = "payment.new"

    PROCESSED_QUEUE: Final[str] = "payments.processed"
    PROCESSED_ROUTING_KEY: Final[str] = "payment.processed"

    def __init__(self, backoff: BackoffSchedule) -> None:
        """Строит описания очередей с общей политикой задержек.

        :param backoff: расписание задержек повторных попыток.
        """
        delays = backoff.delays_ms()
        self._new = WorkQueueTopology(
            queue_name=self.NEW_QUEUE,
            routing_key=self.NEW_ROUTING_KEY,
            exchange_name=self.EXCHANGE,
            dead_letter_exchange_name=self.DEAD_LETTER_EXCHANGE,
            retry_delays_ms=delays,
        )
        self._processed = WorkQueueTopology(
            queue_name=self.PROCESSED_QUEUE,
            routing_key=self.PROCESSED_ROUTING_KEY,
            exchange_name=self.EXCHANGE,
            dead_letter_exchange_name=self.DEAD_LETTER_EXCHANGE,
            retry_delays_ms=delays,
        )

    @property
    def new_payments(self) -> WorkQueueTopology:
        """Очередь новых платежей (потребитель — processor-service)."""
        return self._new

    @property
    def processed_payments(self) -> WorkQueueTopology:
        """Очередь результатов обработки (потребитель — payments-service)."""
        return self._processed

    def all(self) -> tuple[WorkQueueTopology, ...]:
        """Все рабочие очереди системы — для объявления при старте."""
        return self._new, self._processed
