"""Системные часы."""

from datetime import UTC, datetime

from payments_service.application.ports import Clock


class UtcClock(Clock):
    """Текущее время в UTC."""

    def now(self) -> datetime:
        """Текущий момент с таймзоной UTC."""
        return datetime.now(UTC)
