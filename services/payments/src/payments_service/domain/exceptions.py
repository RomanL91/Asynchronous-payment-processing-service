"""Доменные исключения."""


class DomainError(Exception):
    """Нарушение доменного инварианта."""


class InvalidMoneyError(DomainError):
    """Сумма не положительна или имеет больше двух знаков после запятой."""


class InvalidIdempotencyKeyError(DomainError):
    """Ключ идемпотентности пуст или слишком длинный."""
