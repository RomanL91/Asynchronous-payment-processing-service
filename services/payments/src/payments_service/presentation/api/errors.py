"""Отображение исключений сценариев на HTTP-ответы."""

from dataclasses import dataclass

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from payments_service.application.exceptions import IdempotencyConflictError, PaymentNotFoundError
from payments_service.domain import DomainError
from payments_service.presentation.api.schemas import ErrorResponse


@dataclass(frozen=True, slots=True)
class _ErrorMapping:
    """HTTP-код и машинный код ошибки."""

    status_code: int
    code: str


class ExceptionHttpMapper:
    """Реестр «тип исключения → HTTP-ответ».

    Роутеры не содержат ``try/except``: сценарий бросает прикладное
    исключение, реестр превращает его в ответ. Новое исключение —
    новая строка регистрации (OCP).
    """

    def __init__(self) -> None:
        """Создаёт пустой реестр."""
        self._mappings: dict[type[Exception], _ErrorMapping] = {}

    @classmethod
    def default(cls) -> "ExceptionHttpMapper":
        """Реестр исключений payments-service."""
        return (
            cls()
            .register(PaymentNotFoundError, status.HTTP_404_NOT_FOUND, "payment_not_found")
            .register(IdempotencyConflictError, status.HTTP_409_CONFLICT, "idempotency_key_conflict")
            .register(DomainError, 422, "domain_rule_violation")
        )

    def register(self, exc_type: type[Exception], status_code: int, code: str) -> "ExceptionHttpMapper":
        """Регистрирует отображение (fluent)."""
        self._mappings[exc_type] = _ErrorMapping(status_code, code)
        return self

    def install(self, app: FastAPI) -> None:
        """Подключает обработчики к приложению."""
        for exc_type in self._mappings:
            app.add_exception_handler(exc_type, self._handle)

    async def _handle(self, request: Request, exc: Exception) -> JSONResponse:
        """Строит JSON-ответ по ближайшему зарегистрированному типу в MRO."""
        mapping = next(self._mappings[cls] for cls in type(exc).__mro__ if cls in self._mappings)
        body = ErrorResponse(code=mapping.code, detail=str(exc))
        return JSONResponse(status_code=mapping.status_code, content=body.model_dump())
