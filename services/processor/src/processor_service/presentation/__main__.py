"""Запуск процессора: ``python -m processor_service.presentation``."""

import asyncio

from processor_service.presentation.app import ProcessorApplicationFactory


def main() -> None:
    """Точка входа процесса."""
    asyncio.run(ProcessorApplicationFactory().create().run())


if __name__ == "__main__":
    main()
