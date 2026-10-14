"""Читатели проекций (read side CQRS)."""

from payments_service.infrastructure.db.readers.payments import SqlAlchemyPaymentReader

__all__ = ["SqlAlchemyPaymentReader"]
