"""Test PostgreSQL overlap enforcement, with every inserted row rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import randbelow

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from barberbot.db_settings import database_url, get_settings, selected_target


def main() -> None:
    if selected_target() != "test":
        raise RuntimeError(
            "Safety guard: DB smoke check can run only on the test database"
        )

    engine = create_engine(
        database_url(get_settings(), target="test"), hide_parameters=True
    )
    try:
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                # All temporary fixtures are in a transaction, always rolled back.
                user_id = connection.execute(
                    text("INSERT INTO users (telegram_id) VALUES (:tid) RETURNING id"),
                    {"tid": -(10**15 + randbelow(10**12))},
                ).scalar_one()
                barber_id = connection.execute(
                    text("INSERT INTO barbers (name) VALUES (:name) RETURNING id"),
                    {"name": "__smoke_barber_" + str(randbelow(10**12))},
                ).scalar_one()
                service_id = connection.execute(
                    text("""INSERT INTO services (name, price_rub, duration_minutes)
                             VALUES (:name, 1, 60) RETURNING id"""),
                    {"name": "__smoke_service_" + str(randbelow(10**12))},
                ).scalar_one()
                start = datetime(2028, 1, 3, 9, 0, tzinfo=UTC)
                insert_booking = text("""
                    INSERT INTO bookings
                        (user_id, barber_id, service_id, starts_at, ends_at,
                         price_rub_at_booking, duration_minutes_at_booking)
                    VALUES (:user_id, :barber_id, :service_id, :start, :end, 1, 60)
                """)
                args = {
                    "user_id": user_id,
                    "barber_id": barber_id,
                    "service_id": service_id,
                    "start": start,
                    "end": start + timedelta(minutes=60),
                }
                connection.execute(insert_booking, args)

                savepoint = connection.begin_nested()
                try:
                    connection.execute(
                        insert_booking,
                        {
                            **args,
                            "start": start + timedelta(minutes=30),
                            "end": start + timedelta(minutes=90),
                        },
                    )
                except IntegrityError as exc:
                    savepoint.rollback()
                    if getattr(exc.orig, "sqlstate", None) != "23P01":
                        raise AssertionError("Unexpected integrity error") from exc
                else:
                    savepoint.rollback()
                    raise AssertionError(
                        "Database accepted overlapping confirmed bookings"
                    )
            finally:
                trans.rollback()
    finally:
        engine.dispose()
    print(
        "Test database smoke check passed: PostgreSQL rejected overlapping bookings (23P01)."
    )


if __name__ == "__main__":
    main()
