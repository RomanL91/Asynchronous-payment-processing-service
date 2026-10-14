"""Провайдеры зависимостей FastAPI из контейнера."""

from fastapi import Request

from payments_service.application.commands import RegisterPaymentHandler
from payments_service.application.queries import GetPaymentHandler
from payments_service.bootstrap import PaymentsContainer


class ContainerProvider:
    """Достаёт обработчики из контейнера, сохранённого в ``app.state``.

    Обработчики не имеют состояния запроса, поэтому один экземпляр
    обслуживает все конкурентные запросы event loop.
    """

    @staticmethod
    def container(request: Request) -> PaymentsContainer:
        """Контейнер приложения."""
        return request.app.state.container

    @classmethod
    async def register_payment(cls, request: Request) -> RegisterPaymentHandler:
        """Команда регистрации платежа."""
        return cls.container(request).register_payment

    @classmethod
    async def get_payment(cls, request: Request) -> GetPaymentHandler:
        """Запрос деталей платежа."""
        return cls.container(request).get_payment
