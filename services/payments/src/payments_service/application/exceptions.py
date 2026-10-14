"""Исключения прикладного слоя."""

from uuid import UUID


class ApplicationError(Exception):
    """Базовая ошибка сценария."""


class PaymentNotFoundError(ApplicationError):
    """Платёж с указанным идентификатором не существует."""

    def __init__(self, payment_id: UUID) -> None:
        """:param payment_id: искомый идентификатор."""
        super().__init__(f"Платёж {payment_id} не найден")
        self.payment_id = payment_id


class IdempotencyConflictError(ApplicationError):
    """Ключ идемпотентности уже использован с другим телом запроса."""

    def __init__(self, key: str) -> None:
        """:param key: повторно использованный ключ."""
        super().__init__(f"Idempotency-Key {key!r} уже использован с другими параметрами платежа")
        self.key = key
