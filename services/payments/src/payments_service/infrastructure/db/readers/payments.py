"""Чтение проекции платежа."""

from uuid import UUID

from sqlalchemy import select

from payments_service.application.ports import PaymentReader
from payments_service.application.read_models import PaymentDetails
from payments_service.infrastructure.db.database import Database
from payments_service.infrastructure.db.models import PaymentModel


class SqlAlchemyPaymentReader(PaymentReader):
    """Выбирает только нужные колонки и сразу строит DTO.

    Без ORM-объектов, identity map и доменной модели: чтение не
    создаёт агрегат и не открывает транзакцию записи.
    """

    _COLUMNS = (
        PaymentModel.id,
        PaymentModel.amount,
        PaymentModel.currency,
        PaymentModel.description,
        PaymentModel.metadata_.label("metadata"),
        PaymentModel.status,
        PaymentModel.idempotency_key,
        PaymentModel.webhook_url,
        PaymentModel.created_at,
        PaymentModel.processed_at,
        PaymentModel.webhook_delivered_at,
    )

    def __init__(self, database: Database) -> None:
        """:param database: источник сессий."""
        self._database = database

    async def get_details(self, payment_id: UUID) -> PaymentDetails | None:
        """Один ``SELECT`` по первичному ключу."""
        async with self._database.session() as session:
            row = (await session.execute(select(*self._COLUMNS).where(PaymentModel.id == payment_id))).one_or_none()
        return PaymentDetails(**row._asdict()) if row else None
