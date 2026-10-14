"""ORM-модели таблиц ``payments`` и ``outbox``.

Индексы и почему они именно такие:

* ``payments.id`` (PK, UUIDv7) — точечный поиск в GET и в consumer;
* ``uq_payments_idempotency_key`` — уникальность ключа и опора
  ``ON CONFLICT``; одновременно индекс поиска при повторе;
* ``ix_outbox_pending`` — **частичный** индекс по ``created_at`` только
  для неопубликованных строк. Relay читает «первые N неопубликованных»,
  и индекс остаётся крошечным, сколько бы истории ни накопилось.

Статус и валюта хранятся как ``VARCHAR`` + ``CHECK`` (``native_enum=False``):
добавление значения — это изменение CHECK, без ``ALTER TYPE`` и его
ограничений внутри транзакции.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, Integer, MetaData, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from payments_service.domain import Currency, PaymentStatus

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс моделей с единым соглашением об именах ограничений.

    Предсказуемые имена нужны Alembic, чтобы миграции удаляли и
    переименовывали ограничения детерминированно.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _string_enum(enum_cls: type, name: str, length: int) -> Enum:
    """Enum как VARCHAR с CHECK-ограничением по значениям."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class PaymentModel(Base):
    """Таблица платежей."""

    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(_string_enum(Currency, "currency", 3), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[PaymentStatus] = mapped_column(_string_enum(PaymentStatus, "payment_status", 16), nullable=False)
    webhook_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)


class OutboxModel(Base):
    """Таблица transactional outbox."""

    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_outbox_pending", "created_at", postgresql_where=text("published_at IS NULL")),)
