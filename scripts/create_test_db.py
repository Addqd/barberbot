"""Create the isolated <POSTGRES_DB>_test database if it does not exist.

Never deletes an existing database. Run via `uv run poe db-test-create`.
"""

from __future__ import annotations

import psycopg
from psycopg import sql

from barberbot.db_settings import database_names, get_settings


def main() -> None:
    settings = get_settings()
    main_name, test_name = database_names(settings)
    if not test_name.endswith("_test") or test_name == main_name:
        raise RuntimeError("Unsafe test database name")

    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname="postgres",  # PostgreSQL maintenance database
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (test_name,)
        ).fetchone()
        if exists:
            print(f"Test database {test_name} already exists; unchanged.")
        else:
            # The database name is safely quoted by psycopg.sql.Identifier.
            # PostgreSQL identifiers cannot be bound as query parameters.
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_name))
            )
            print(f"Test database {test_name} created.")


if __name__ == "__main__":
    main()
