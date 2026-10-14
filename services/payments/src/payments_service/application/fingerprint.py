"""Вычисление отпечатка тела запроса."""

import hashlib
import json
from typing import Any

from payments_service.domain import Money, RequestFingerprint


class RequestFingerprintCalculator:
    """Строит SHA-256 от канонического представления запроса.

    Канонизация делает отпечаток независимым от порядка ключей JSON и
    формы записи суммы (``100``, ``100.0`` и ``100.00`` — один запрос).
    """

    def calculate(
        self,
        *,
        money: Money,
        description: str,
        metadata: dict[str, Any],
        webhook_url: str,
    ) -> RequestFingerprint:
        """Вычисляет отпечаток.

        :return: hex SHA-256 канонического JSON.
        """
        canonical = json.dumps(
            {
                "amount": money.normalized_amount(),
                "currency": money.currency.value,
                "description": description,
                "metadata": metadata,
                "webhook_url": webhook_url,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return RequestFingerprint(hashlib.sha256(canonical.encode()).hexdigest())
