"""Idempotent demo seed: services, barbers, weekday schedules; no ORM.

Execute only through the existing Poe tasks db-seed / db-test-seed.
ON CONFLICT DO NOTHING preserves admin edits when rerun.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import create_engine, text

from barberbot.db_settings import database_url, get_settings, selected_target

SERVICES = (
    ("Обычная стрижка", 500, 60),
    ("Стрижка с укладкой", 650, 60),
    ("Стрижка с мытьём волос", 800, 60),
)
BARBERS = ("Елена", "Максим", "Милана")


def main() -> None:
    settings = get_settings()
    target = selected_target()
    engine = create_engine(database_url(settings, target=target), hide_parameters=True)
    try:
        with engine.begin() as connection:
            for name, price, duration in SERVICES:
                connection.execute(
                    text("""
                        INSERT INTO services (name, price_rub, duration_minutes)
                        VALUES (:name, :price, :duration)
                        ON CONFLICT (name) DO NOTHING
                    """),
                    {"name": name, "price": price, "duration": duration},
                )
            for name in BARBERS:
                connection.execute(
                    text("""
                        INSERT INTO barbers (name) VALUES (:name)
                        ON CONFLICT (name) DO NOTHING
                    """),
                    {"name": name},
                )
                barber_id = connection.execute(
                    text("SELECT id FROM barbers WHERE name = :name"),
                    {"name": name},
                ).scalar_one()
                for weekday in range(5):  # Monday = 0, Friday = 4
                    connection.execute(
                        text("""
                            INSERT INTO barber_working_hours
                                (barber_id, weekday, start_time, end_time)
                            VALUES (:barber_id, :weekday, :start_time, :end_time)
                            ON CONFLICT (barber_id, weekday) DO NOTHING
                        """),
                        {
                            "barber_id": barber_id,
                            "weekday": weekday,
                            "start_time": time(9, 0),
                            "end_time": time(17, 0),
                        },
                    )
    finally:
        engine.dispose()
    print(f"Demo seed applied to {target} database (existing rows preserved).")


if __name__ == "__main__":
    main()
