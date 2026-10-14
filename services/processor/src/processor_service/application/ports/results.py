"""Порт публикации результата обработки."""

from abc import ABC, abstractmethod

from broker_kit.contracts import PaymentProcessedV1


class ProcessingResultPublisher(ABC):
    """Отправляет результат обработки владельцу платежа."""

    @abstractmethod
    async def publish(self, event: PaymentProcessedV1) -> None:
        """Публикует событие и возвращается после подтверждения брокера."""
