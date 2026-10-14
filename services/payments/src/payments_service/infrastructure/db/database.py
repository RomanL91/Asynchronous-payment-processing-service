"""Движок и фабрика сессий."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """Владелец пула соединений и фабрики сессий.

    Один экземпляр на процесс; закрывается при остановке приложения.
    ``expire_on_commit=False`` — данные остаются доступны после
    ``commit`` без повторного обращения к БД (в async это обязательно:
    неявный refresh вызвал бы ошибку вне greenlet-контекста).
    """

    def __init__(self, url: str, *, pool_size: int = 10, max_overflow: int = 5, echo: bool = False) -> None:
        """Создаёт движок.

        :param url: DSN с драйвером ``postgresql+asyncpg``.
        :param pool_size: постоянный размер пула.
        :param max_overflow: дополнительные соединения при пиках.
        :param echo: логировать SQL.
        """
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            echo=echo,
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False, autoflush=False)

    @property
    def engine(self) -> AsyncEngine:
        """Асинхронный движок."""
        return self._engine

    def session(self) -> AsyncSession:
        """Новая сессия (одна на Unit of Work или запрос чтения)."""
        return self._session_factory()

    async def dispose(self) -> None:
        """Закрывает все соединения пула."""
        await self._engine.dispose()
