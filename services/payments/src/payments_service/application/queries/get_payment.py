"""Запрос детальной информации о платеже."""

from dataclasses import dataclass
from uuid import UUID

from payments_service.application.exceptions import PaymentNotFoundError
from payments_service.application.ports import PaymentReader
from payments_service.application.read_models import PaymentDetails


@dataclass(frozen=True, slots=True)
class GetPaymentQuery:
    """Идентификатор запрашиваемого платежа."""

    payment_id: UUID


class GetPaymentHandler:
    """Возвращает проекцию платежа через порт чтения."""

    def __init__(self, reader: PaymentReader) -> None:
        """:param reader: читатель проекций."""
        self._reader = reader

    async def handle(self, query: GetPaymentQuery) -> PaymentDetails:
        """Ищет платёж.

        :raises PaymentNotFoundError: платежа нет.
        """
        details = await self._reader.get_details(query.payment_id)
        if details is None:
            raise PaymentNotFoundError(query.payment_id)
        return details
