"""Manual migrations for PostgreSQL, with read-only ORM metadata.

``target_metadata`` reflects the ORM models so a future, explicitly authorized
``alembic revision --autogenerate`` can compare them with the database.
Autogenerate itself stays unavailable: the schema is still authored by hand in
``alembic/versions`` and the PostgreSQL exclusion constraint remains
migration-owned.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from barberbot.db import Base
from barberbot.db_settings import database_url, get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # URL rendered only in-memory; never printed/logged.
    url = database_url(get_settings())
    context.configure(
        url=url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        database_url(get_settings()),
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
