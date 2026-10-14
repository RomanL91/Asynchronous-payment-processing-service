"""Настройка трассировки и бизнес-теги спанов."""

from uuid import UUID

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from broker_kit.observability import TraceTags, TracingConfigurator

PAYMENT_ID = UUID("7f3c9a1e-0000-4000-8000-000000000001")


def test_build_without_endpoint_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без OTEL_EXPORTER_OTLP_ENDPOINT трассировка выключена."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    assert TracingConfigurator("processor").build() is None


def test_build_with_endpoint_sets_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """С endpoint провайдер подписывает спаны именем сервиса."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")

    provider = TracingConfigurator("processor").build()

    assert provider is not None
    assert provider.resource.attributes["service.name"] == "processor"
    provider.shutdown()


def test_tag_payment_sets_attribute_on_current_span(spans: InMemorySpanExporter) -> None:
    """payment.id попадает на текущий спан строкой."""
    with trace.get_tracer(__name__).start_as_current_span("work"):
        TraceTags.tag_payment(PAYMENT_ID)

    (span,) = spans.get_finished_spans()
    assert span.attributes[TraceTags.PAYMENT_ID] == str(PAYMENT_ID)


def test_tag_payment_without_span_is_noop() -> None:
    """Вне спана вызов безопасен."""
    TraceTags.tag_payment(PAYMENT_ID)
