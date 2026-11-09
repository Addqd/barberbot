"""SQLAlchemy 2.x ORM-модели существующей схемы BarberBot.

Источник истины по схеме — Alembic-миграция ``0001_initial_schema``.
Модели описывают те же таблицы, столбцы, типы, ограничения и связи.
``metadata.create_all()`` в проекте не вызывается: владелец схемы — Alembic.

Ограничение ``ex_bookings_barber_no_overlap`` объявлено в metadata для полноты
описания, но создаётся/удаляется только миграцией. Оно защищает от
пересекающихся активных записей одного мастера на уровне PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from barberbot.db.base import Base


class BookingStatus(StrEnum):
    """Статусы записи (значения совпадают с ``ck_bookings_status``)."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class ReminderStatus(StrEnum):
    """Статусы напоминания (значения совпадают с ``ck_reminders_status``)."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Статусы, при которых запись занимает время мастера.
ACTIVE_BOOKING_STATUSES: tuple[BookingStatus, ...] = (
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
)


def _status_type(enum_class: type[StrEnum], *, name: str) -> Enum:
    """Тип VARCHAR(16) со значениями enum, без создания нового типа в БД."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        length=16,
        create_constraint=False,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class User(Base):
    """Пользователь Telegram."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="user")


class Barber(Base):
    """Мастер барбершопа."""

    __tablename__ = "barbers"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    working_hours: Mapped[list[BarberWorkingHours]] = relationship(
        back_populates="barber", passive_deletes=True
    )
    time_off: Mapped[list[BarberTimeOff]] = relationship(
        back_populates="barber", passive_deletes=True
    )
    bookings: Mapped[list[Booking]] = relationship(back_populates="barber")


class Service(Base):
    """Услуга барбершопа с ценой и длительностью."""

    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("price_rub >= 0", name="ck_services_price_nonnegative"),
        CheckConstraint(
            "duration_minutes BETWEEN 1 AND 60", name="ck_services_duration_1_60"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    price_rub: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    bookings: Mapped[list[Booking]] = relationship(back_populates="service")


class BarberWorkingHours(Base):
    """Недельный график мастера. ``weekday``: 0 = понедельник ... 6 = воскресенье."""

    __tablename__ = "barber_working_hours"
    __table_args__ = (
        UniqueConstraint("barber_id", "weekday", name="uq_barber_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
        CheckConstraint("start_time < end_time", name="ck_working_hours_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    barber: Mapped[Barber] = relationship(back_populates="working_hours")


class BarberTimeOff(Base):
    """Исключение в графике мастера (отпуск, отсутствие)."""

    __tablename__ = "barber_time_off"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_time_off_order"),
        Index("ix_time_off_barber_starts", "barber_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))

    barber: Mapped[Barber] = relationship(back_populates="time_off")


class Booking(Base):
    """Запись клиента к мастеру.

    ``price_rub_at_booking`` и ``duration_minutes_at_booking`` — снимок условий
    услуги на момент записи: последующие изменения услуги их не затрагивают.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("starts_at < ends_at", name="ck_bookings_time_order"),
        CheckConstraint(
            "price_rub_at_booking >= 0", name="ck_bookings_price_nonnegative"
        ),
        CheckConstraint(
            "duration_minutes_at_booking BETWEEN 1 AND 60",
            name="ck_bookings_duration_1_60",
        ),
        CheckConstraint(
            "status IN ('confirmed','cancelled','completed')",
            name="ck_bookings_status",
        ),
        Index("ix_bookings_user_starts", "user_id", "starts_at"),
        Index("ix_bookings_barber_starts", "barber_id", "starts_at"),
        # Создаётся и удаляется только Alembic-миграцией.
        ExcludeConstraint(
            (text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            ("barber_id", "="),
            using="gist",
            where=text("status IN ('confirmed', 'completed')"),
            name="ex_bookings_barber_no_overlap",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    barber_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("barbers.id", ondelete="RESTRICT"), nullable=False
    )
    service_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_rub_at_booking: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_minutes_at_booking: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )
    status: Mapped[BookingStatus] = mapped_column(
        _status_type(BookingStatus, name="booking_status"),
        nullable=False,
        server_default=text("'confirmed'"),
        default=BookingStatus.CONFIRMED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="bookings")
    barber: Mapped[Barber] = relationship(back_populates="bookings")
    service: Mapped[Service] = relationship(back_populates="bookings")
    reminder: Mapped[Reminder | None] = relationship(
        back_populates="booking", uselist=False, passive_deletes=True
    )


class Reminder(Base):
    """Напоминание о записи (доставка — вне рамок GROUP II)."""

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','sent','failed','cancelled')",
            name="ck_reminders_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_reminders_attempts"),
        Index("ix_reminders_status_remind_at", "status", "remind_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(
        _status_type(ReminderStatus, name="reminder_status"),
        nullable=False,
        server_default=text("'pending'"),
        default=ReminderStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'"), default=0
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    booking: Mapped[Booking] = relationship(back_populates="reminder")


__all__ = [
    "ACTIVE_BOOKING_STATUSES",
    "Barber",
    "BarberTimeOff",
    "BarberWorkingHours",
    "Booking",
    "BookingStatus",
    "Reminder",
    "ReminderStatus",
    "Service",
    "User",
]
