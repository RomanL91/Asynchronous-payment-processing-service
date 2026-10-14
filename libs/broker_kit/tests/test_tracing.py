"""Трассировка через брокер из RabbitBrokerFactory (in-memory)."""

from faststream.rabbit import TestRabbitBroker
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from broker_kit.factory import RabbitBrokerFactory
from broker_kit.reliability import (
    FailurePolicy,
    PermanentError,
    ReliableMessageExecutor,
    ReliableSubscription,
    RetryPublisher,
    TransientError,
    TypeBasedErrorClassifier,
)
from broker_kit.settings import BrokerSettings
from broker_kit.topology import WorkQueueTopology


class _FlakyHandler:
    """Падает на первой попытке; запоминает trace_id, видимый внутри обработчика."""

    def __init__(self) -> None:
        self.trace_ids: list[int] = []

    async def handle(self, message) -> None:
        self.trace_ids.append(trace.get_current_span().get_span_context().trace_id)
        if len(self.trace_ids) == 1:
            raise TransientError("первая попытка")


def _mentions(span: ReadableSpan, queue_name: str) -> bool:
    """Спан относится к очереди: FastStream включает её в имя спана."""
    return queue_name in span.name


def _ancestor_ids(span: ReadableSpan, by_id: dict[int, ReadableSpan]) -> set[int]:
    """span_id всех предков спана."""
    ids: set[int] = set()
    while span.parent is not None and span.parent.span_id in by_id:
        span = by_id[span.parent.span_id]
        ids.add(span.context.span_id)
    return ids


async def test_failed_attempt_is_error_and_retry_is_its_descendant(
    topology: WorkQueueTopology, spans: InMemorySpanExporter
) -> None:
    """Обработка — в трейсе публикации; упавшая попытка ERROR; ретрай — её потомок."""
    broker = RabbitBrokerFactory(BrokerSettings()).create()
    handler = _FlakyHandler()
    policy = FailurePolicy.default(TypeBasedErrorClassifier(), RetryPublisher(broker))
    ReliableSubscription(broker, topology, handler, ReliableMessageExecutor(topology, policy)).register()
    retry_queue = topology.retry_queue_after(1)

    @broker.subscriber(retry_queue)
    async def capture_retry(body: dict) -> None:
        """Получатель копии: в in-memory брокере TTL не эмулируется."""

    async with TestRabbitBroker(broker) as test_broker:
        await test_broker.publish(
            {"payment_id": "42"}, exchange=topology.exchange(), routing_key=topology.routing_key, message_id="m-1"
        )

    finished = spans.get_finished_spans()
    by_id = {s.context.span_id: s for s in finished}
    failed = [s for s in finished if s.kind is SpanKind.CONSUMER and s.status.status_code is StatusCode.ERROR]
    retry_consumed = [s for s in finished if s.kind is SpanKind.CONSUMER and _mentions(s, retry_queue.name)]

    assert len({s.context.trace_id for s in finished}) == 1, "все спаны — один трейс"
    assert handler.trace_ids == [finished[0].context.trace_id], "обработчик видит текущий трейс"
    assert len(failed) == 1, "упавшая попытка помечена ERROR"
    assert len(retry_consumed) == 1
    assert failed[0].context.span_id in _ancestor_ids(retry_consumed[0], by_id), "ретрай — потомок упавшей попытки"


class _RejectingHandler:
    """Всегда постоянная ошибка — сообщение сразу уходит в DLQ."""

    async def handle(self, message) -> None:
        raise PermanentError("невалидное тело")


async def test_failed_attempt_records_dlq_outcome(topology: WorkQueueTopology, spans: InMemorySpanExporter) -> None:
    """Уход в DLQ делает брокер (reject → DLX), публикации нет — исход виден атрибутом спана."""
    broker = RabbitBrokerFactory(BrokerSettings()).create()
    policy = FailurePolicy.default(TypeBasedErrorClassifier(), RetryPublisher(broker))
    ReliableSubscription(broker, topology, _RejectingHandler(), ReliableMessageExecutor(topology, policy)).register()

    async with TestRabbitBroker(broker) as test_broker:
        await test_broker.publish({}, exchange=topology.exchange(), routing_key=topology.routing_key, message_id="m-2")

    (failed,) = [s for s in spans.get_finished_spans() if s.status.status_code is StatusCode.ERROR]
    assert str(failed.attributes.get(ReliableMessageExecutor.OUTCOME_ATTRIBUTE)).startswith("DLQ")
