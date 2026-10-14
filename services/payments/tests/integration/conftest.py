"""Подготовка БД для интеграционных тестов.

Требуется переменная ``TEST_DATABASE_URL`` (asyncpg DSN пустой тестовой БД);
без неё тесты пропускаются. Схема создаётся из метаданных моделей, таблицы
очищаются перед каждым тестом.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from payments_service.infrastructure.db import Database
from payments_service.infrastructure.db.models import Base

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[Database]:
    """Пул соединений к тестовой БД со свежей схемой."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL не задан")
    db = Database(TEST_DATABASE_URL, pool_size=20)
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@pytest.fixture(autouse=True)
async def clean_tables(database: Database) -> None:
    """Очищает таблицы перед тестом."""
    async with database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE payments, outbox"))
