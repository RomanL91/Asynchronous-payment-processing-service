"""Запуск consumer результатов: ``python -m payments_service.presentation.consumer``."""

import asyncio

from payments_service.presentation.consumer.app import ConsumerApplicationFactory


def main() -> None:
    """Точка входа процесса."""
    asyncio.run(ConsumerApplicationFactory().create().run())


if __name__ == "__main__":
    main()
