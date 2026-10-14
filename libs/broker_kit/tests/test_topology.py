"""Тесты описания топологии и расписания задержек."""

import pytest

from broker_kit.reliability import DeliveryAttempt, ExponentialBackoff
from broker_kit.topology import WorkQueueTopology


class TestExponentialBackoff:
    """Расписание экспоненциальных задержек."""

    def test_delays_grow_exponentially(self) -> None:
        """Три попытки дают две задержки: 1 с и 2 с."""
        assert ExponentialBackoff(1000, 2, 3).delays_ms() == (1000, 2000)

    def test_single_attempt_has_no_retries(self) -> None:
        """Одна попытка — повторов нет."""
        assert ExponentialBackoff(1000, 2, 1).delays_ms() == ()


class TestWorkQueueTopology:
    """Аргументы очередей, от которых зависит маршрутизация."""

    def test_main_queue_dead_letters_into_dlx(self, topology: WorkQueueTopology) -> None:
        """Отклонённое сообщение основной очереди уходит в DLX под именем очереди."""
        arguments = topology.main_queue().arguments
        assert arguments["x-dead-letter-exchange"] == "payments.dlx"
        assert arguments["x-dead-letter-routing-key"] == "payments.new"

    def test_retry_queue_returns_message_to_main_exchange(self, topology: WorkQueueTopology) -> None:
        """По истечении TTL сообщение возвращается в основной обменник."""
        retry = topology.retry_queue_after(2)
        assert retry.name == "payments.new.retry.2"
        assert (
            retry.arguments.items()
            >= {
                "x-message-ttl": 2000,
                "x-dead-letter-exchange": "payments",
                "x-dead-letter-routing-key": "payment.new",
            }.items()
        )

    def test_no_retry_queue_after_last_attempt(self, topology: WorkQueueTopology) -> None:
        """После последней попытки retry-очереди нет."""
        with pytest.raises(ValueError):
            topology.retry_queue_after(3)


class TestDeliveryAttempt:
    """Восстановление номера попытки из заголовков."""

    @pytest.mark.parametrize(
        ("headers", "expected"),
        [({}, 1), ({"x-attempt": 2}, 2), ({"x-attempt": "3"}, 3), ({"x-attempt": "мусор"}, 1), (None, 1)],
    )
    def test_from_headers(self, headers: dict | None, expected: int) -> None:
        """Отсутствующий и битый заголовок трактуются как первая попытка."""
        assert DeliveryAttempt.from_headers(headers).number == expected
