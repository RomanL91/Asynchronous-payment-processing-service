"""Генератор UUID версии 7 (RFC 9562)."""

import os
import time
from uuid import UUID

from payments_service.application.ports import IdGenerator


class UuidV7Generator(IdGenerator):
    """UUIDv7: 48 бит миллисекунд Unix-времени + 74 случайных бита.

    Почему не UUIDv4: значения v7 растут во времени, поэтому новые
    первичные ключи дописываются в правую часть B-tree индекса. С v4
    вставки разбросаны по всему индексу — больше page split, хуже
    локальность буферного кэша и больше WAL.
    """

    _VERSION = 0x7
    _VARIANT = 0b10

    def new_id(self) -> UUID:
        """Новый UUIDv7."""
        timestamp_ms = time.time_ns() // 1_000_000
        random_bits = int.from_bytes(os.urandom(10), "big")
        rand_a = (random_bits >> 62) & 0xFFF
        rand_b = random_bits & ((1 << 62) - 1)
        value = (
            (timestamp_ms & ((1 << 48) - 1)) << 80 | self._VERSION << 76 | rand_a << 64 | self._VARIANT << 62 | rand_b
        )
        return UUID(int=value)
