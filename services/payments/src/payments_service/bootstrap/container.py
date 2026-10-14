"""DI-контейнер payments-service."""

import logging
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
from payments_service.application.commands import (
    ApplyProcessingResultHandler,
    DeliverWebhookHandler,
    RegisterPaymentHandler,
)
from payments_service.application.commands.register_payment import IdempotentReplayGuard
from payments_service.application.exceptions import PaymentNotFoundError
from payments_service.application.fingerprint import RequestFingerprintCalculator
from payments_service.application.integration import OutboxMessageMapper
from payments_service.application.ports import UnitOfWork, WebhookPermanentlyRejectedError
from payments_service.application.queries import GetPaymentHandler
from payments_service.config import PaymentsSettings
from payments_service.domain import DomainError
from payments_service.infrastructure.db import Database, SqlAlchemyUnitOfWork
from payments_service.infrastructure.db.readers import SqlAlchemyPaymentReader
from payments_service.infrastructure.outbox import (
    EventRoutingTable,
    OutboxRelay,
    OutboxRelayWorker,
    RabbitOutboxPublisher,
)
from payments_service.infrastructure.system import UtcClock, UuidV7Generator
from payments_service.infrastructure.webhook import HttpxWebhookSender, WebhookResponsePolicy
from payments_service.presentation.consumer.handler import PaymentProcessedMessageHandler


class PaymentsContainer:
    """Ленивый граф зависимостей.

    Компоненты создаются при первом обращении (``cached_property``),
    поэтому каждый процесс поднимает только нужное: API не подключается
    к RabbitMQ, relay не создаёт HTTP-клиент webhook.
    """

    def __init__(
        self,
        settings: PaymentsSettings,
        broker_settings: BrokerSettings,
        logger: logging.Logger | None = None,
    ) -> None:
        """Сохраняет настройки."""
        self.settings = settings
        self.broker_settings = broker_settings
        self._logger = logger or logging.getLogger("payments-service")

    # --- общая инфраструктура -------------------------------------------------

    @cached_property
    def database(self) -> Database:
        """Пул соединений PostgreSQL."""
        return Database(
            self.settings.database_url,
            pool_size=self.settings.database_pool_size,
            max_overflow=self.settings.database_max_overflow,
        )

    def unit_of_work(self) -> UnitOfWork:
        """Фабрика Unit of Work (передаётся в сценарии как callable)."""
        return SqlAlchemyUnitOfWork(self.database)

    @cached_property
    def clock(self) -> UtcClock:
        """Часы."""
        return UtcClock()

    @cached_property
    def ids(self) -> UuidV7Generator:
        """Генератор UUIDv7."""
        return UuidV7Generator()

    # --- API ------------------------------------------------------------------

    @cached_property
    def register_payment(self) -> RegisterPaymentHandler:
        """Команда регистрации платежа."""
        return RegisterPaymentHandler(
            uow_factory=self.unit_of_work,
            clock=self.clock,
            ids=self.ids,
            fingerprints=RequestFingerprintCalculator(),
            outbox_mapper=OutboxMessageMapper(self.ids),
            replay_guard=IdempotentReplayGuard(),
        )

    @cached_property
    def get_payment(self) -> GetPaymentHandler:
        """Запрос деталей платежа."""
        return GetPaymentHandler(SqlAlchemyPaymentReader(self.database))

    # --- брокер ---------------------------------------------------------------

    @cached_property
    def topology(self) -> PaymentsTopology:
        """Топология RabbitMQ."""
        backoff = ExponentialBackoff(
            base_delay_ms=self.broker_settings.retry_base_delay_ms,
            multiplier=self.broker_settings.retry_multiplier,
            max_attempts=self.broker_settings.retry_max_attempts,
        )
        return PaymentsTopology(backoff)

    @cached_property
    def broker(self) -> RabbitBroker:
        """Брокер с publisher confirms и ручным ack."""
        return RabbitBrokerFactory(self.broker_settings).create()

    @cached_property
    def topology_declarer(self) -> TopologyDeclarer:
        """Объявление всей топологии при старте процесса."""
        return TopologyDeclarer(self.broker, self.topology.all())

    # --- relay ----------------------------------------------------------------

    @cached_property
    def outbox_relay(self) -> OutboxRelay:
        """Публикация одной пачки outbox."""
        return OutboxRelay(
            uow_factory=self.unit_of_work,
            publisher=RabbitOutboxPublisher(self.broker, EventRoutingTable.from_topology(self.topology)),
            clock=self.clock,
            batch_size=self.settings.outbox_batch_size,
        )

    @cached_property
    def outbox_relay_worker(self) -> OutboxRelayWorker:
        """Цикл outbox relay."""
        return OutboxRelayWorker(self.outbox_relay, self.settings.outbox_poll_interval_s)

    # --- consumer результатов -------------------------------------------------

    @cached_property
    def http_client(self) -> httpx.AsyncClient:
        """Общий HTTP-клиент webhook (с трассировкой запросов)."""
        client = httpx.AsyncClient(timeout=self.settings.webhook_timeout_s, follow_redirects=False)
        HTTPXClientInstrumentor.instrument_client(client)
        return client

    @cached_property
    def apply_processing_result(self) -> ApplyProcessingResultHandler:
        """Команда применения результата с доставкой webhook."""
        webhook_delivery = DeliverWebhookHandler(
            uow_factory=self.unit_of_work,
            sender=HttpxWebhookSender(self.http_client, WebhookResponsePolicy()),
            clock=self.clock,
        )
        return ApplyProcessingResultHandler(self.unit_of_work, webhook_delivery)

    @cached_property
    def processed_payments_subscription(self) -> ReliableSubscription:
        """Подписка на ``payments.processed`` с ретраями и DLQ."""
        topology = self.topology.processed_payments
        classifier = TypeBasedErrorClassifier(
            permanent=(PaymentNotFoundError, WebhookPermanentlyRejectedError, DomainError, ValueError),
        )
        policy = FailurePolicy.default(classifier, RetryPublisher(self.broker))
        return ReliableSubscription(
            broker=self.broker,
            topology=topology,
            handler=PaymentProcessedMessageHandler(self.apply_processing_result),
            executor=ReliableMessageExecutor(topology, policy),
        )

    # --- завершение -----------------------------------------------------------

    async def aclose(self) -> None:
        """Освобождает только реально созданные ресурсы."""
        if "http_client" in self.__dict__:
            await self.http_client.aclose()
        if "database" in self.__dict__:
            await self.database.dispose()
