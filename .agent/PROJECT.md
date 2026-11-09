# BarberBot — stable project context

## Goal

Build a small, demonstrable Telegram booking system for **one barbershop**.
The project should show practical business logic and reliable persistence,
without unnecessary product scope.

## Confirmed MVP

### Client
- See the three services and their configured prices.
- Select a service, barber, day and available appointment time.
- Create a booking; view and cancel own bookings.
- Receive an appointment reminder.

### Administrator
- Manage services and their prices.
- Manage barbers' schedules and customer appointments.

### Booking invariants
- A barber must never have overlapping appointments.
- Service duration affects the available appointment slots.
- Concurrency must not create double bookings.
- Users may only manage their own bookings unless explicitly authorized as admin.

## Confirmed technology and development mode

- Python + aiogram 3.x (Telegram interface, FSM where useful).
- PostgreSQL, SQLAlchemy, Alembic.
- Bot runs locally on the user's Windows PC during development.
- Telegram Long Polling; no public endpoint, paid hosting, domain or HTTPS
  certificate is required for local polling development.
- Python project, dependencies, `.venv`, Poe tasks, `compose.yaml` and `.env` are
  prepared by the user; Pi must not install, update or reconfigure them.
- Git is fully owned by the user; Pi performs no Git/GitHub operations.

## Explicit MVP exclusions

No online payments, loyalty system, AI assistant, full CRM, or additional business
locations unless the user changes the scope.

## Open decisions — do not invent

- Exact prices, durations, operating hours and timezone.
- Admin identities and authorization bootstrap.
- Reminder timing and delivery/retry policies.
- Persistence/service layer layout (to be chosen in the database task).

## Confirmed architecture — TASK 001 (bot bootstrap)

- Python package `barberbot/`, entry point `python -m barberbot` (Poe task `dev`).
- Modules: `config.py` (settings), `logging_setup.py`, `keyboards.py`,
  `app.py` (Bot/Dispatcher wiring and runtime), `handlers/` (routers and handlers).
- Configuration uses `pydantic-settings` + `aiogram` token validation:
  - `BOT_TOKEN` is required, stored in `SecretStr`, stripped, and format-checked
    with `aiogram.utils.token.validate_token` (no regex duplication).
  - `extra="ignore"` is deliberate: `POSTGRES_*` already live in `.env` and must
    not fail validation while the bot has no database access.
  - Validation failures become `ConfigurationError` built from field names only,
    raised `from None`, so values never reach messages or tracebacks.
- Handlers are registered in routers built by factories (`build_router()`),
  because an aiogram `Router` can only have one parent; fresh instances keep
  `build_dispatcher()` reusable (tests, restarts).
- Main menu buttons use one callback handler with a fixed `F.data.in_(...)` set;
  every callback is answered explicitly via `callback.answer(...)`.
- Global error handler (`dispatcher.errors`) logs the exception with traceback
  and sends only a generic Russian message to the user.
- Shutdown path: aiogram handles Ctrl+C (`handle_signals=True`), then our
  `finally` closes the bot session (`close_bot_session=False` + explicit close).
- Runtime failure of Telegram connectivity is reported by `__main__` as a clear
  log message and non-zero exit code, not as an unhandled traceback.
- Testing: pytest + pytest-asyncio with a `FakeSession` (`BaseSession` subclass)
  that records Bot API method objects. No network, no Telegram, no PostgreSQL.
- No database models, migrations, FSM, webhook or extra dependencies in TASK 001.

## Confirmed architecture — GROUP II (ORM, data layer, booking engine)

- Schema ownership stays with Alembic (`alembic/versions/0001_initial_schema`).
  `metadata.create_all()` / `drop_all()` are never used in application code.
  `alembic/env.py` now exposes `target_metadata = Base.metadata` so a future,
  explicitly authorized autogenerate can compare models with the database;
  autogenerate was not invoked and no migration was added or edited.
- The PostgreSQL exclusion constraint `ex_bookings_barber_no_overlap` is the
  final safeguard against double booking. It is declared in ORM metadata for
  completeness but remains migration-owned. SQLSTATE `23P01` is translated into
  the domain error `SlotUnavailable` after the transaction rollback.
- Typed SQLAlchemy 2.x ORM in `barberbot/db/models.py` mirrors all seven tables,
  including column types, PKs, named unique/check constraints, indexes, FKs and
  relationships. Status columns are `StrEnum` values stored in `VARCHAR(16)`
  ("confirmed/cancelled/completed", "pending/sent/failed/cancelled") without a
  PostgreSQL enum type, matching the existing check constraints.
- `barberbot/db/engine.py` builds one `AsyncEngine` (Psycopg 3, `pool_pre_ping`,
  `hide_parameters`) and an `async_sessionmaker(expire_on_commit=False)`.
  Connection settings come from `barberbot/db_settings.py` + `.env`; credentials
  are never duplicated in code. The caller owns the engine lifecycle and must
  call `Database.dispose()` on shutdown (wiring into the bot runtime is GROUP III).
- Data access is a thin repository layer in `barberbot/db/repositories.py`
  (`UserRepository`, `CatalogRepository`, `ScheduleRepository`,
  `BookingRepository`). Repositories receive an `AsyncSession`; there is no
  Unit of Work or abstract interface layer.
- `barberbot/booking/service.py` owns business rules and creates one
  `AsyncSession` per operation, using `async with session.begin()` for writes.
  Pure slot rules live in `barberbot/booking/slots.py` and are unit-tested
  without a database.
- Booking policy (enforced in the service, not the schema): 30-minute start
  grid, Mon–Fri working hours from `barber_working_hours`, service duration from
  `services`, `Europe/Moscow` via `zoneinfo` (`tzdata` on Windows), no past
  starts, half-open `[start, end)` intervals, `barber_time_off` respected,
  cancellation allowed only by the owner and no later than 2 hours before start.
- Domain errors in `barberbot/booking/errors.py` are distinct and contain only
  Russian user-facing text: no SQL, DSN, credentials or DB internals.
- Windows 10 requires `SelectorEventLoop` for Psycopg async. `barberbot/__main__.py`
  passes it to `asyncio.run`, and `tests/conftest.py` provides it through
  `pytest_asyncio_loop_factories`.
- Integration tests run against `<POSTGRES_DB>_test` only. The `database` fixture
  verifies `current_database()` before yielding and fails hard on mismatch.
  Test rows use unique `__test_...` names / negative Telegram IDs and are deleted
  by a factory fixture; seeded demo data is never modified.
- Concurrency is tested with independent sessions/connections: two simultaneous
  requests for one slot (exactly one success), direct overlapping inserts
  (one `23P01`), and different barbers at the same time (both succeed).
- `reminders` is mapped as ORM but reminder scheduling/delivery is not
  implemented; Telegram FSM booking stays in GROUP III.

## Environment note

- On the development machine direct TCP access to `api.telegram.org:443` is
  blocked; the system proxy (WinINET) can reach it, but aiohttp/aiogram does not
  use the WinINET proxy. Live polling therefore requires direct Telegram access
  or explicit proxy support, which is not implemented in TASK 001.

## Agent and user workflow

- Global Pi rules + project-local `AGENTS.md`.
- `.agent/TASK.md` = local, temporary checklist; do not commit.
- Pi **never** performs Git or GitHub operations, including status/diff.
- User owns Git and installation; ChatGPT prepares prompts, reviews and ZIP fixes.

Update this file only for confirmed, durable architectural/product decisions.
