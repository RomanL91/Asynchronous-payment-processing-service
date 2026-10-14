"""Сборка FastAPI-приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from broker_kit.observability import LoggingConfigurator, TracingConfigurator
from broker_kit.settings import BrokerSettings
from payments_service.bootstrap import PaymentsContainer
from payments_service.config import PaymentsSettings
from payments_service.presentation.api.errors import ExceptionHttpMapper
from payments_service.presentation.api.routes import PaymentsController
from payments_service.presentation.api.security import ApiKeyGuard


class ApiApplicationFactory:
    """Строит приложение: контейнер в lifespan, ключ на всех маршрутах API."""

    def __init__(
        self,
        settings: PaymentsSettings | None = None,
        container: PaymentsContainer | None = None,
    ) -> None:
        """Сохраняет настройки; контейнер можно подменить в тестах."""
        self._settings = settings or PaymentsSettings()
        self._container = container

    def create(self) -> FastAPI:
        """Создаёт приложение."""
        logger = LoggingConfigurator("payments-api", self._settings.log_level).configure()
        TracingConfigurator("payments-api").configure()
        container = self._container or PaymentsContainer(self._settings, BrokerSettings(), logger)

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            """Публикует контейнер в ``app.state`` и закрывает ресурсы при остановке."""
            app.state.container = container
            try:
                yield
            finally:
                await container.aclose()

        app = FastAPI(
            title="Payments Service",
            version="1.0.0",
            description="Асинхронный процессинг платежей: приём, идемпотентность, статус.",
            lifespan=lifespan,
        )
        guard = ApiKeyGuard(self._settings.api_key.get_secret_value())
        app.include_router(PaymentsController().router, dependencies=[Depends(guard)])
        app.add_api_route("/health", self._health, methods=["GET"], include_in_schema=False)
        ExceptionHttpMapper.default().install(app)
        return app

    @staticmethod
    async def _health() -> dict[str, str]:
        """Проверка живости для docker healthcheck: процесс отвечает, БД не трогаем."""
        return {"status": "ok"}


def create_app() -> FastAPI:
    """Фабрика для ``uvicorn --factory``."""
    return ApiApplicationFactory().create()
