"""Порт чтения проекций (read side CQRS)."""

from abc import ABC, abstractmethod
from uuid import UUID

from payments_service.application.read_models import PaymentDetails


class PaymentReader(ABC):
    """Читает данные платежей для отображения, без доменной модели."""

    @abstractmethod
    async def get_details(self, payment_id: UUID) -> PaymentDetails | None:
        """Возвращает проекцию платежа или ``None``."""
