"""In-memory хранилище списаний."""

from gateway_mock.application.ports import ChargeStore
from gateway_mock.domain import Charge


class InMemoryChargeStore(ChargeStore):
    """Словарь в памяти процесса.

    Достаточно для эмулятора в одном экземпляре. У реального PSP это
    персистентная БД с уникальным индексом по ключу идемпотентности.
    """

    def __init__(self) -> None:
        """Создаёт пустое хранилище."""
        self._charges: dict[str, Charge] = {}

    async def get(self, idempotency_key: str) -> Charge | None:
        """Списание по ключу."""
        return self._charges.get(idempotency_key)

    async def save(self, charge: Charge) -> None:
        """Сохраняет списание."""
        self._charges[charge.idempotency_key] = charge

    def __len__(self) -> int:
        """Число проведённых списаний."""
        return len(self._charges)
