"""Перевод доменных событий в интеграционные (anti-corruption на выходе)."""

from payments_service.application.integration.mapper import OutboxMessageMapper

__all__ = ["OutboxMessageMapper"]
