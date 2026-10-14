"""FastAPI-приложение эмулятора шлюза."""

from typing import Annotated

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from gateway_mock.application import ChargeService, KeyedLock
from gateway_mock.config import GatewaySettings
from gateway_mock.domain import (
    ChargeRequest,
    GatewayOverloadedError,
    IdempotencyMismatchError,
    ProbabilisticFaultInjector,
    RandomOutcomeStrategy,
    UniformLatencyStrategy,
)
from gateway_mock.infrastructure import InMemoryChargeStore
from gateway_mock.presentation.schemas import ChargeRequestBody, ChargeResponseBody


class ChargesController:
    """``POST /v1/charges`` — идемпотентное списание."""

    def __init__(self, service: ChargeService) -> None:
        """:param service: сценарий списания."""
        self._service = service

    async def create(
        self,
        body: ChargeRequestBody,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    ) -> ChargeResponseBody:
        """Проводит списание или возвращает сохранённое."""
        result = await self._service.charge(
            ChargeRequest(
                idempotency_key=idempotency_key,
                amount=body.amount,
                currency=body.currency,
                description=body.description,
            )
        )
        response.headers["Idempotent-Replayed"] = str(result.replayed).lower()
        return ChargeResponseBody.from_charge(result.charge)


class GatewayApiFactory:
    """Собирает приложение и его зависимости."""

    def __init__(self, settings: GatewaySettings | None = None, service: ChargeService | None = None) -> None:
        """Сохраняет настройки; сервис можно подменить в тестах."""
        self._settings = settings or GatewaySettings()
        self._service = service

    def create(self) -> FastAPI:
        """Создаёт приложение."""
        controller = ChargesController(self._service or self._build_service())
        app = FastAPI(title="Payment Gateway Mock", version="1.0.0")
        app.add_api_route("/v1/charges", controller.create, methods=["POST"], response_model=ChargeResponseBody)
        app.add_api_route("/health", self._health, methods=["GET"], include_in_schema=False)
        app.add_exception_handler(GatewayOverloadedError, self._overloaded)
        app.add_exception_handler(IdempotencyMismatchError, self._mismatch)
        return app

    def _build_service(self) -> ChargeService:
        """Сервис с настраиваемыми стратегиями эмуляции."""
        settings = self._settings
        return ChargeService(
            store=InMemoryChargeStore(),
            locks=KeyedLock(),
            outcome=RandomOutcomeStrategy(settings.success_rate),
            latency=UniformLatencyStrategy(settings.min_latency_s, settings.max_latency_s),
            faults=ProbabilisticFaultInjector(settings.transient_failure_rate),
        )

    @staticmethod
    async def _health() -> dict[str, str]:
        """Проверка живости для docker healthcheck."""
        return {"status": "ok"}

    @staticmethod
    async def _overloaded(request: Request, exc: Exception) -> JSONResponse:
        """503 + Retry-After для временного сбоя."""
        return JSONResponse(status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "1"})

    @staticmethod
    async def _mismatch(request: Request, exc: Exception) -> JSONResponse:
        """422 для повторного ключа с другими параметрами."""
        return JSONResponse(status_code=422, content={"detail": str(exc)})


def create_app() -> FastAPI:
    """Фабрика для ``uvicorn --factory``."""
    return GatewayApiFactory().create()


__all__ = ["ChargesController", "GatewayApiFactory", "create_app"]
