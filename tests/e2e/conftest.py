"""Общие фикстуры e2e."""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope="session")
def _span_exporter() -> InMemorySpanExporter:
    """Глобальный провайдер с in-memory экспортёром (ставится один раз на сессию)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(_span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    """Экспортёр, очищенный перед тестом."""
    _span_exporter.clear()
    return _span_exporter
