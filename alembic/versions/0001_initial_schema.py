"""Initial BarberBot schema with DB-enforced non-overlapping bookings.

Revision ID: 0001_initial_schema
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Needed for bigint equality in a GiST exclusion constraint.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "barbers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("price_rub", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("price_rub >= 0", name="ck_services_price_nonnegative"),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 60", name="ck_services_duration_1_60"
        ),
    )

    op.create_table(
        "barber_working_hours",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "barber_id",
            sa.BigInteger(),
            sa.ForeignKey("barbers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.UniqueConstraint("barber_id", "weekday", name="uq_barber_weekday"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_working_hours_weekday"),
        sa.CheckConstraint("start_time < end_time", name="ck_working_hours_order"),
    )

    op.create_table(
        "barber_time_off",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "barber_id",
            sa.BigInteger(),
            sa.ForeignKey("barbers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.CheckConstraint("starts_at < ends_at", name="ck_time_off_order"),
    )
    op.create_index(
        "ix_time_off_barber_starts", "barber_time_off", ["barber_id", "starts_at"]
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "barber_id",
            sa.BigInteger(),
            sa.ForeignKey("barbers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.BigInteger(),
            sa.ForeignKey("services.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_rub_at_booking", sa.Integer(), nullable=False),
        sa.Column("duration_minutes_at_booking", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="confirmed"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("starts_at < ends_at", name="ck_bookings_time_order"),
        sa.CheckConstraint(
            "price_rub_at_booking >= 0", name="ck_bookings_price_nonnegative"
        ),
        sa.CheckConstraint(
            "duration_minutes_at_booking BETWEEN 1 AND 60",
            name="ck_bookings_duration_1_60",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed','cancelled','completed')", name="ck_bookings_status"
        ),
    )
    # The half-open range [start, end) allows consecutive bookings where
    # one ends exactly when the next starts. Cancelled bookings free slots.
    # The database enforces this even under concurrent transactions.
    op.execute("""
        ALTER TABLE bookings ADD CONSTRAINT ex_bookings_barber_no_overlap
        EXCLUDE USING gist (
            barber_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status IN ('confirmed', 'completed'))
    """)
    op.create_index("ix_bookings_user_starts", "bookings", ["user_id", "starts_at"])
    op.create_index("ix_bookings_barber_starts", "bookings", ["barber_id", "starts_at"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "booking_id",
            sa.BigInteger(),
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','cancelled')",
            name="ck_reminders_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_reminders_attempts"),
    )
    op.create_index(
        "ix_reminders_status_remind_at", "reminders", ["status", "remind_at"]
    )


def downgrade() -> None:
    # Destructive: table contents will be removed. The extension is retained
    # because it may have been installed independently of this migration.
    op.drop_index("ix_reminders_status_remind_at", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("ix_bookings_barber_starts", table_name="bookings")
    op.drop_index("ix_bookings_user_starts", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("ix_time_off_barber_starts", table_name="barber_time_off")
    op.drop_table("barber_time_off")
    op.drop_table("barber_working_hours")
    op.drop_table("services")
    op.drop_table("barbers")
    op.drop_table("users")
