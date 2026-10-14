"""Контроллер ресурса «Платежи»."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from broker_kit.observability import TraceTags
from payments_service.application.commands import RegisterPaymentCommand, RegisterPaymentHandler
from payments_service.application.queries import GetPaymentHandler, GetPaymentQuery
from payments_service.presentation.api.dependencies import ContainerProvider
from payments_service.presentation.api.schemas import (
    CreatePaymentRequest,
    ErrorResponse,
    PaymentAcceptedResponse,
    PaymentResponse,
)

IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[\x21-\x7E]+$",
        description="Уникальный ключ запроса: повтор с тем же ключом не создаёт новый платёж.",
    ),
]


class PaymentsController:
    """Тонкий контроллер: HTTP ↔ команды/запросы, без бизнес-логики.

    Маршруты регистрируются методами экземпляра, а не модульными
    функциями: контроллер — обычный класс, его зависимости явны.
    """

    REPLAY_HEADER = "Idempotent-Replayed"

    def __init__(self) -> None:
        """Создаёт роутер и регистрирует маршруты."""
        self.router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
        self.router.add_api_route(
            "",
            self.create,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=PaymentAcceptedResponse,
            summary="Создать платёж",
            responses={
                status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Ключ занят другим запросом"},
            },
        )
        self.router.add_api_route(
            "/{payment_id}",
            self.get,
            methods=["GET"],
            response_model=PaymentResponse,
            summary="Получить платёж",
            responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
        )

    async def create(
        self,
        body: CreatePaymentRequest,
        idempotency_key: IdempotencyKeyHeader,
        response: Response,
        handler: Annotated[RegisterPaymentHandler, Depends(ContainerProvider.register_payment)],
    ) -> PaymentAcceptedResponse:
        """Принимает платёж в асинхронную обработку.

        Повтор с тем же ключом и телом возвращает тот же платёж
        (с заголовком ``Idempotent-Replayed: true``); с другим телом — 409.
        """
        acceptance = await handler.handle(
            RegisterPaymentCommand(
                idempotency_key=idempotency_key,
                amount=body.amount,
                currency=body.currency,
                description=body.description,
                metadata=body.metadata,
                webhook_url=str(body.webhook_url),
            )
        )
        TraceTags.tag_payment(acceptance.payment_id)
        response.headers[self.REPLAY_HEADER] = str(acceptance.replayed).lower()
        return PaymentAcceptedResponse.from_acceptance(acceptance)

    async def get(
        self,
        payment_id: UUID,
        handler: Annotated[GetPaymentHandler, Depends(ContainerProvider.get_payment)],
    ) -> PaymentResponse:
        """Возвращает текущее состояние платежа."""
        return PaymentResponse.from_details(await handler.handle(GetPaymentQuery(payment_id)))
