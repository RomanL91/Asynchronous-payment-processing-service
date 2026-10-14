"""Запуск relay: ``python -m payments_service.presentation.relay``."""

import asyncio

from payments_service.presentation.relay.app import RelayApplication


def main() -> None:
    """Точка входа процесса."""
    asyncio.run(RelayApplication().run())


if __name__ == "__main__":
    main()
