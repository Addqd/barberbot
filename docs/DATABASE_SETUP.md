# BarberBot — PostgreSQL and Alembic (Windows 10 / PowerShell)

This archive contains **only new/changed files**, with paths relative to
`D:\repos\Telegram\barberbot`. Extract into the project root. It **does not**
contain `.env`, a real bot token, Git files, or an ORM.

The updated `pyproject.toml` was assembled from the version of `feature`
reviewed on GitHub on 2026-11-09. If you have subsequently edited it, compare
the task section before replacing your local file. No dependencies were added.

## Run (in order)

```powershell
cd D:\repos\Telegram\barberbot
uv run poe db-up
uv run poe db-upgrade
uv run poe db-seed
uv run poe db-test-create
uv run poe db-test-upgrade
uv run poe db-test-seed
uv run poe db-test-smoke
uv run poe db-current
uv run poe db-test-current
```

The existing `.env` must have `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`. `BOT_TOKEN` is **not** needed by
migrations/seeding. No new environment variables must be added to `.env`.

The test database name is derived as `POSTGRES_DB + "_test"` (normally
`barberbot_test`) and uses the same local PostgreSQL container. Test database
creation is safe to rerun; it never deletes an existing database.

## Poe commands

| Main database | Test database | Purpose |
| --- | --- | --- |
| `uv run poe db-upgrade` | `uv run poe db-test-upgrade` | Apply pending revisions |
| `uv run poe db-downgrade` | `uv run poe db-test-downgrade` | Downgrade **one** revision, may delete data |
| `uv run poe db-current` | `uv run poe db-test-current` | Show currently applied revision |
| `uv run poe db-seed` | `uv run poe db-test-seed` | Insert demo rows if missing |
| — | `uv run poe db-test-create` | Create test database if missing |
| — | `uv run poe db-test-smoke` | Check exclusion constraint in rollback-only transaction |
| — | `uv run poe db-test-empty` | **DESTRUCTIVE**: remove all test tables and contents |

Shared revision commands:

```powershell
uv run poe db-history
uv run poe db-heads
uv run poe db-revision -m "describe change"
```

`db-revision` produces a new **empty** Alembic revision; edit its `upgrade()`
and `downgrade()` manually. Do **not** use `--autogenerate` until Pi adds ORM
metadata and configures `target_metadata` in `alembic/env.py`.

### Schema/data changes and deletion

The same revision mechanism handles table creation, adding/changing/removing
columns, and versioned UPDATE/DELETE/INSERT operations. Alembic is **not** a
CRUD interface: runtime booking changes/cancellations will use the service
layer and ORM added later. A data-only revision could contain:

```python
def upgrade() -> None:
    op.execute("UPDATE services SET price_rub = 550 WHERE name = 'Обычная стрижка'")


def downgrade() -> None:
    op.execute("UPDATE services SET price_rub = 500 WHERE name = 'Обычная стрижка'")
```

This example is documentation **only**; no price changes are included.
For destructive data migrations, design a safe `downgrade()` that restores
data when possible, otherwise document irreversibility. Always back up data
before dropping tables/columns or deleting records.

### Reset isolated test schema (DELETES ALL TEST DATA)

```powershell
uv run poe db-test-empty
uv run poe db-test-upgrade
uv run poe db-test-seed
```

There is intentionally **no destructive shortcut for the main database**.
A main-database downgrade remains available one migration at a time, but it
must be used carefully. `db-down` stops Docker without removing its volume.

## What the first migration creates

- `users`: Telegram users (no seed users).
- `barbers`: three demo barbers: Елена, Максим, Милана.
- `services`: three services; prices 500/650/800 RUB and **60 minutes each**.
- `barber_working_hours`: Mon–Fri 09:00–17:00 for each barber.
- `barber_time_off`: individual absences/exceptions.
- `bookings`: references to users/barbers/services, status and price snapshot.
- `reminders`: persistent status to support later notification scheduling.

All date-time instants use PostgreSQL `timestamptz`; future application code
must convert presentation and calendar rules using `Europe/Moscow`. Weekdays
are encoded Monday=0 ... Sunday=6. Available starts use a 30-minute grid.
Cancellation is permitted no later than 2 hours before start. **Those last
three booking policies are NOT yet implemented/enforced by the database**;
Pi must enforce them in the booking service (Group II).

PostgreSQL itself prevents overlapping **confirmed or completed** bookings
for the same barber using an exclusion constraint over `tstzrange` with
half-open bounds `[start, end)`. Cancelled bookings do not reserve time.

### Integration notes for Pi

- Do NOT create tables with `metadata.create_all()` in app code: Alembic
  remains the schema owner.
- Future SQLAlchemy ORM models must **match this schema**, including names,
  constraints and column types. Configure `target_metadata` for subsequent
  `--autogenerate` only after ORM models exist and have been reviewed.
- Ensure transaction isolation and catch PostgreSQL exclusion violations
  (`SQLSTATE 23P01`) as booking conflicts, not unhandled errors.
- Maintain a separate test database; never run integration cleanup on main.
- A successful offline SQL rendering is not a substitute for actually
  running migrations and checking constraints against PostgreSQL.
