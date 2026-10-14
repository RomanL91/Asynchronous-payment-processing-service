"""Тесты политики ошибок и исполнителя."""

from pydantic import BaseModel

from broker_kit.reliability import (
    FailurePolicy,
    PermanentError,
    ReliableMessageExecutor,
    TransientError,
    TypeBasedErrorClassifier,
)
from broker_kit.topology import WorkQueueTopology
from tests.conftest import FakeMessage, RecordingRetryPublisher


class _Handler:
    """Обработчик, бросающий заданное исключение."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def handle(self, message: FakeMessage) -> None:
        """Падает, если задана ошибка."""
        if self._error is not None:
            raise self._error


class _DomainNotFound(Exception):
    """Прикладная ошибка, объявленная сервисом постоянной."""


def _executor(topology: WorkQueueTopology, publisher: RecordingRetryPublisher) -> ReliableMessageExecutor:
    classifier = TypeBasedErrorClassifier(permanent=(_DomainNotFound,))
    return ReliableMessageExecutor(topology, FailurePolicy.default(classifier, publisher))


class TestReliableMessageExecutor:
    """Сквозные сценарии завершения доставки."""

    async def test_success_acks(self, topology: WorkQueueTopology) -> None:
        """Успешная обработка подтверждается."""
        message, publisher = FakeMessage(), RecordingRetryPublisher()
        await _executor(topology, publisher).execute(message, _Handler())
        assert message.outcome == "ack"

    async def test_transient_error_goes_to_first_retry_queue(self, topology: WorkQueueTopology) -> None:
        """Временная ошибка первой попытки → retry.1, следующая попытка — вторая."""
        message, publisher = FakeMessage(), RecordingRetryPublisher()
        await _executor(topology, publisher).execute(message, _Handler(TransientError("503")))
        assert publisher.calls == [("payments.new.retry.1", 2)]
        assert message.outcome == "ack"

    async def test_unknown_error_is_retried(self, topology: WorkQueueTopology) -> None:
        """Неизвестная ошибка считается временной."""
        message, publisher = FakeMessage(headers={"x-attempt": 2}), RecordingRetryPublisher()
        await _executor(topology, publisher).execute(message, _Handler(ConnectionError()))
        assert publisher.calls == [("payments.new.retry.2", 3)]

    async def test_last_attempt_goes_to_dlq(self, topology: WorkQueueTopology) -> None:
        """Третья неудачная попытка — reject без requeue (DLX → DLQ)."""
        message, publisher = FakeMessage(headers={"x-attempt": 3}), RecordingRetryPublisher()
        await _executor(topology, publisher).execute(message, _Handler(TransientError()))
        assert publisher.calls == []
        assert message.outcome == "reject(requeue=False)"

    async def test_permanent_errors_skip_retries(self, topology: WorkQueueTopology) -> None:
        """Постоянные ошибки (в т.ч. сервисные и валидации) сразу в DLQ."""

        class _Body(BaseModel):
            value: int

        try:
            _Body.model_validate_json(b'{"value": "x"}')
        except Exception as validation_error:
            errors: list[Exception] = [PermanentError(), _DomainNotFound(), validation_error]
        for error in errors:
            message, publisher = FakeMessage(), RecordingRetryPublisher()
            await _executor(topology, publisher).execute(message, _Handler(error))
            assert message.outcome == "reject(requeue=False)", error
            assert publisher.calls == []

    async def test_failed_retry_publication_requeues(self, topology: WorkQueueTopology) -> None:
        """Если не удалось опубликовать копию — сообщение возвращается в очередь."""
        message, publisher = FakeMessage(), RecordingRetryPublisher(fail=True)
        await _executor(topology, publisher).execute(message, _Handler(TransientError()))
        assert message.outcome == "nack(requeue=True)"
