"""Асинхронные блокировки по ключу."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _Entry:
    """Блокировка и число её текущих пользователей."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    holders: int = 0


class KeyedLock:
    """Реестр ``asyncio.Lock`` по строковому ключу с подсчётом ссылок.

    Запись удаляется, когда последний ожидающий освобождает ключ, —
    реестр не растёт бесконечно. Всё выполняется в одном event loop без
    точек переключения между проверкой и изменением словаря, поэтому
    дополнительной синхронизации самого реестра не требуется.
    """

    def __init__(self) -> None:
        """Создаёт пустой реестр."""
        self._entries: dict[str, _Entry] = {}

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        """Захватывает блокировку ключа на время блока ``async with``."""
        entry = self._entries.setdefault(key, _Entry())
        entry.holders += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.holders -= 1
            if entry.holders == 0:
                del self._entries[key]

    def __len__(self) -> int:
        """Число ключей с активными пользователями."""
        return len(self._entries)
