"""Классификация HTTP-ответа получателя webhook."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from payments_service.application.ports import (
    WebhookDeliveryError,
    WebhookPermanentlyRejectedError,
    WebhookTemporarilyUnavailableError,
)


@dataclass(frozen=True, slots=True)
class _StatusRule:
    """Правило: предикат по коду ответа → тип ошибки (``None`` — успех)."""

    matches: Callable[[int], bool]
    error: type[WebhookDeliveryError] | None


class WebhookResponsePolicy:
    """Таблица правил по коду ответа (первое совпадение побеждает).

    * 2xx — доставлено;
    * 408, 425, 429, 5xx — временно недоступно, повторяем;
    * прочее (3xx, 4xx) — получатель отверг, повтор бессмыслен → DLQ.
    """

    _DEFAULT_RULES: Sequence[_StatusRule] = (
        _StatusRule(lambda code: 200 <= code < 300, None),
        _StatusRule(lambda code: code in {408, 425, 429} or code >= 500, WebhookTemporarilyUnavailableError),
        _StatusRule(lambda code: True, WebhookPermanentlyRejectedError),
    )

    def __init__(self, rules: Sequence[_StatusRule] | None = None) -> None:
        """:param rules: правила; по умолчанию — стандартные."""
        self._rules = tuple(rules or self._DEFAULT_RULES)

    def ensure_delivered(self, status_code: int, url: str) -> None:
        """Ничего не делает при успехе, иначе бросает классифицированную ошибку.

        :raises WebhookTemporarilyUnavailableError: временная ошибка.
        :raises WebhookPermanentlyRejectedError: постоянная ошибка.
        """
        rule = next(rule for rule in self._rules if rule.matches(status_code))
        if rule.error is not None:
            raise rule.error(f"Webhook {url} ответил HTTP {status_code}")
