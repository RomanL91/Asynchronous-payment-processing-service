"""Окружение Alembic в асинхронном режиме (asyncpg)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from payments_service.config import PaymentsSettings
from payments_service.infrastructure.db.models import Base


class MigrationRunner:
    """Запускает миграции онлайн (через соединение) или офлайн (генерация SQL)."""

    def __init__(self) -> None:
        """Читает конфигурацию Alembic и DSN из настроек сервиса."""
        self._config = context.config
        if self._config.config_file_name is not None:
            fileConfig(self._config.config_file_name)
        self._url = PaymentsSettings().database_url
        self._metadata = Base.metadata

    def run(self) -> None:
        """Выбирает режим запуска."""
        if context.is_offline_mode():
            self._run_offline()
        else:
            asyncio.run(self._run_online())

    def _run_offline(self) -> None:
        """Генерирует SQL без подключения к БД."""
        context.configure(url=self._url, target_metadata=self._metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()

    async def _run_online(self) -> None:
        """Применяет миграции через асинхронный движок."""
        engine = create_async_engine(self._url)
        try:
            async with engine.connect() as connection:
                await connection.run_sync(self._apply)
        finally:
            await engine.dispose()

    def _apply(self, connection: Connection) -> None:
        """Синхронная часть: Alembic работает поверх sync-фасада соединения."""
        context.configure(connection=connection, target_metadata=self._metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


MigrationRunner().run()
