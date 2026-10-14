"""Аутентификация по статическому ключу ``X-API-Key``."""

import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = "X-API-Key"
_API_KEY_SCHEME = APIKeyHeader(name=API_KEY_HEADER, auto_error=False, description="Статический API-ключ сервиса.")


class ApiKeyGuard:
    """Зависимость FastAPI, проверяющая ``X-API-Key``.

    Сравнение через ``secrets.compare_digest`` — постоянное время,
    без утечки длины совпавшего префикса по таймингу.
    Экземпляр вызываемый, поэтому подключается как ``Depends(guard)``.
    """

    def __init__(self, expected_key: str) -> None:
        """:param expected_key: допустимый ключ."""
        if not expected_key:
            raise ValueError("API-ключ не может быть пустым")
        self._expected = expected_key.encode()

    async def __call__(self, provided: Annotated[str | None, Security(_API_KEY_SCHEME)]) -> None:
        """Пропускает запрос или отвечает 401.

        :raises HTTPException: ключ отсутствует или неверен.
        """
        if provided is None or not secrets.compare_digest(provided.encode(), self._expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный или отсутствующий X-API-Key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
