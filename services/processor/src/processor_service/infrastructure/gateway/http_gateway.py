"""Клиент платёжного шлюза по HTTP."""

from datetime import datetime

import httpx
from pydantic import BaseModel

from processor_service.application.ports import GatewayRejectedError, GatewayUnavailableError, PaymentGateway
from processor_service.domain import ChargeOutcome, ChargeRequest, ChargeStatus


class _ChargeResponse(BaseModel):
    """Тело успешного ответа шлюза."""

    charge_id: str
    status: ChargeStatus
    processed_at: datetime


class HttpPaymentGateway(PaymentGateway):
    """Вызывает ``POST /v1/charges`` с заголовком ``Idempotency-Key``.

    Классификация ответов:

    * 200 — результат (``succeeded``/``failed``); заголовок
      ``Idempotent-Replayed: true`` означает повтор;
    * 408, 425, 429, 5xx, сетевые ошибки, таймаут — временный сбой;
    * прочие 4xx — запрос отклонён.
    """

    _RETRYABLE = frozenset({408, 425, 429})

    def __init__(self, client: httpx.AsyncClient) -> None:
        """:param client: клиент с ``base_url`` шлюза и таймаутом."""
        self._client = client

    async def charge(self, request: ChargeRequest) -> ChargeOutcome:
        """Проводит списание."""
        try:
            response = await self._client.post(
                "/v1/charges",
                json={
                    "amount": str(request.amount),
                    "currency": request.currency,
                    "description": request.description,
                },
                headers={"Idempotency-Key": request.idempotency_key},
            )
        except httpx.HTTPError as error:
            raise GatewayUnavailableError(f"Шлюз недоступен: {type(error).__name__}") from error
        self._ensure_success(response)
        body = _ChargeResponse.model_validate_json(response.content)
        return ChargeOutcome(
            charge_id=body.charge_id,
            status=body.status,
            processed_at=body.processed_at,
            replayed=response.headers.get("Idempotent-Replayed") == "true",
        )

    def _ensure_success(self, response: httpx.Response) -> None:
        """Бросает классифицированную ошибку для не-2xx ответов."""
        code = response.status_code
        if 200 <= code < 300:
            return
        if code in self._RETRYABLE or code >= 500:
            raise GatewayUnavailableError(f"Шлюз ответил HTTP {code}")
        raise GatewayRejectedError(f"Шлюз отклонил запрос: HTTP {code} {response.text[:200]}")
