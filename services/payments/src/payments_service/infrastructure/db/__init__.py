"""Хранилище PostgreSQL на SQLAlchemy 2.0 в асинхронном режиме.

Принципы доступа к данным:

* только явные запросы, без lazy loading — N+1 невозможен по построению
  (``lazy="raise"`` не нужен: в моделях нет relationship);
* массовые операции outbox — одним ``INSERT`` / ``UPDATE … WHERE id = ANY``;
* идемпотентность — ``INSERT … ON CONFLICT DO NOTHING`` по уникальному индексу;
* конкурентный relay — ``FOR UPDATE SKIP LOCKED`` по частичному индексу.
"""

from payments_service.infrastructure.db.database import Database
from payments_service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

__all__ = ["Database", "SqlAlchemyUnitOfWork"]
