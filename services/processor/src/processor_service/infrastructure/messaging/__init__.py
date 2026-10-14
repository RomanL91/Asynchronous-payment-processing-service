"""Публикация результатов обработки в RabbitMQ."""

from processor_service.infrastructure.messaging.result_publisher import RabbitResultPublisher

__all__ = ["RabbitResultPublisher"]
