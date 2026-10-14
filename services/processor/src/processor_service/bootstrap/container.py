"""DI-контейнер processor-service."""

from functools import cached_property

import httpx
from faststream.rabbit import RabbitBroker
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from broker_kit.factory import RabbitBrokerFactory
from broker_kit.reliability import (
    ExponentialBackoff,
    FailurePolicy,
    ReliableMessageExecutor,
    ReliableSubscription,
    RetryPublisher,
    TypeBasedErrorClassifier,
)
from broker_kit.settings import BrokerSettings
from broker_kit.topology import PaymentsTopology, TopologyDeclarer
from processor_service.application import ProcessPaymentHandler
from processor_service.application.ports import GatewayRejectedError
from processor_service.config import ProcessorSettings
from processor_service.infrastructure.gateway import HttpPaymentGateway
from processor_service.infrastructure.messaging import RabbitResultPublisher
from processor_service.presentation.handler import PaymentCreatedMessageHandler


class ProcessorContainer:
    """Ленивый граф зависимостей процессора."""

    def __init__(self, settings: ProcessorSettings, broker_settings: BrokerSettings) -> None:
        """Сохраняет настройки."""
        self.settings = settings
        self.broker_settings = broker_settings

    @cached_property
    def topology(self) -> PaymentsTopology:
        """Топология RabbitMQ."""
        return PaymentsTopology(
            ExponentialBackoff(
                base_delay_ms=self.broker_settings.retry_base_delay_ms,
                multiplier=self.broker_settings.retry_multiplier,
                max_attempts=self.broker_settings.retry_max_attempts,
            )
        )

    @cached_property
    def broker(self) -> RabbitBroker:
        """Брокер с publisher confirms и ручным ack."""
        return RabbitBrokerFactory(self.broker_settings).create()

    @cached_property
    def topology_declarer(self) -> TopologyDeclarer:
        """Объявление всей топологии при старте."""
        return TopologyDeclarer(self.broker, self.topology.all())

    @cached_property
    def http_client(self) -> httpx.AsyncClient:
        """HTTP-клиент шлюза с пулом keep-alive соединений и трассировкой запросов."""
        client = httpx.AsyncClient(base_url=self.settings.gateway_url, timeout=self.settings.gateway_timeout_s)
        HTTPXClientInstrumentor.instrument_client(client)
        return client

    @cached_property
    def process_payment(self) -> ProcessPaymentHandler:
        """Сценарий обработки платежа."""
        return ProcessPaymentHandler(
            gateway=HttpPaymentGateway(self.http_client),
            publisher=RabbitResultPublisher(self.broker, self.topology.processed_payments),
        )

    @cached_property
    def new_payments_subscription(self) -> ReliableSubscription:
        """Подписка на ``payments.new`` с ретраями и DLQ."""
        topology = self.topology.new_payments
        classifier = TypeBasedErrorClassifier(permanent=(GatewayRejectedError,))
        policy = FailurePolicy.default(classifier, RetryPublisher(self.broker))
        return ReliableSubscription(
            broker=self.broker,
            topology=topology,
            handler=PaymentCreatedMessageHandler(self.process_payment),
            executor=ReliableMessageExecutor(topology, policy),
        )

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент, если он создавался."""
        if "http_client" in self.__dict__:
            await self.http_client.aclose()
