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
- Admin identities and authorization bootstrap — **confirmed in TASK IV.1**:
  `ADMIN_TELEGRAM_IDS` (fail closed, see the admin panel section below).
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
  `create_booking()` is a single atomic transaction: the booking insert and the
  detail reload (`get_with_details`) happen inside the same `begin()` block, so a
  failed reload rolls back the insert and the caller gets `DatabaseUnavailable`
  instead of a phantom committed booking. Pure slot rules live in
  `barberbot/booking/slots.py` and are unit-tested without a database.
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

## Confirmed architecture — GROUP III (client Telegram UI)

- The client UI is implemented in `barberbot/handlers/`: `common.py` (commands,
  main menu), `services.py` (catalog), `booking.py` (FSM scenario),
  `my_bookings.py` (list/card/cancel), `fallback.py` (stale/unknown callbacks),
  `render.py` (edit-or-send helper), and the router order in `__init__.py`
  (fallback last).
- Presentation is separated from the booking engine: `callbacks.py` (typed
  `CallbackData`), `fsm.py` (`BookingFlow`, safe parsing of FSM data),
  `ui.py` (Moscow formatting, statuses, display sorting, UI-only cancel
  eligibility), `messages.py` (Russian texts), `keyboards.py` (all keyboards).
- `BookingService` remains the single source of booking rules. GROUP III only
  added two read-only methods, `list_active_services()` and
  `list_active_barbers()`; slot calculation, creation, listing and cancellation
  are unchanged. Handlers never compute availability themselves.
- Callback data is untrusted: no Telegram ID is carried inside it. The user is
  always identified by `event.from_user.id`. Typed `CallbackData.filter()`
  rejects bad prefixes/fields/types; `StateFilter` binds each button to its FSM
  step; a final catch-all callback handler answers every stale/unknown press so
  no spinner is left. Service IDs, barber IDs, dates and times from callbacks
  are re-checked against fresh DB data before use, and `create_booking()`
  revalidates everything again (exclusion constraint is the final guard).
- Booking flow states: `service → barber → date → time → confirm`. Dates are
  refetched on every page/step (horizon owned by the service), paginated 6 per
  page; time is passed as a Unix timestamp and re-checked against
  `available_slots()`; the day is stored as an ISO date. `START_AT` is stored as
  an ISO datetime with timezone, and the final handler verifies that its Moscow
  date equals the selected day.
- FSM uses aiogram's default in-memory storage (no Redis). State loss is
  tolerated: handlers validate FSM data and restart the scenario with a clear
  message. `/start` clears the state; going back resets dependent keys by
  `state.set_data(...)` at each step.
- Cancellation UI is hint-only: `ui.is_cancellable()` (real clock, status
  `confirmed`, at least 2 hours before start) decides whether to show the
  button, but `BookingService.cancel_booking()` is authoritative. The handler
  also pre-checks status/deadline for clean messages; ownership is enforced by
  looking the booking up in the user's own list and again by the service.
- Double “Подтвердить” is prevented by `StateFilter` (state is cleared after
  success) plus `SimpleEventIsolation` on the dispatcher, which serializes
  updates of the same chat. The PostgreSQL exclusion constraint remains the
  final protection against two bookings for one slot.
- Dependency injection/lifecycle: `build_dispatcher(booking_service)` stores the
  service in `Dispatcher.workflow_data`; handlers receive it by argument name.
  `run_bot()` creates one `Database` per process, builds `BookingService` from
  its session factory, and disposes the engine and closes the Telegram session
  in `finally`, including startup failures. Migrations are never run on bot
  start. `SelectorEventLoop` on Windows is unchanged.
- Tests: `FakeSession` now records `EditMessageText` as well; navigation/command
  tests use `tests/fakes.py::FakeBookingService` without a database. Critical
  flows run through a real `Dispatcher.feed_update` with the real
  `BookingService` against `barberbot_test` only. No Telegram network calls.

## Confirmed architecture — automatic booking completion

- A `confirmed` booking whose service has already ended (`ends_at <= now`,
  timezone-aware) is moved to `completed`. `cancelled` and `completed` rows and
  not-yet-ended `confirmed` rows are never touched. The boundary is inclusive.
- The status change is a single SQL `UPDATE`
  (`WHERE status = 'confirmed' AND ends_at <= now`) executed through the
  existing repository + service layer (`BookingRepository.complete_finished()`,
  `BookingService.complete_finished_bookings()`). PostgreSQL row locking makes
  concurrent runs conflict-free and idempotent; there is no new migration and
  no schema change.
- Scheduling uses the already installed APScheduler 3.x
  (`barberbot/booking/completion.py`, `CompletionScheduler`): the scheduling
  loop is one interval job (1 minute, `coalesce=True`, `max_instances=1`), not a
  separate background-task system. The same class performs one sweep at start,
  so bookings that ended during downtime are completed after a restart.
- Lifecycle: `build_dispatcher()` creates the scheduler and keeps it in
  `workflow_data`; `on_startup` performs the first sweep and starts the
  interval, `on_shutdown` stops it. aiogram emits shutdown in a `finally`, so
  the job is stopped on normal stop and on polling errors as well.
- A temporary database error (`DatabaseUnavailable`) is logged as a warning and
  does not stop the scheduler: the next interval retries. Domain messages stay
  free of SQL/DSN details.
- Booking, cancellation, listing, slot protection and the exclusion constraint
  are unchanged: `completed` remains an active status for slot occupancy.

## Confirmed architecture — private chats only (security fix)

- Client features (catalog, FSM booking, my bookings, cancellation, navigation)
  are reachable only from Telegram `private` chats. The single boundary is
  `PrivateChatOnlyMiddleware` (`barberbot/middleware.py`) registered in
  `build_dispatcher()` as `dispatcher.update.outer_middleware(...)`, so it runs
  for every update before filters, handlers and any `BookingService` call.
- Chat type comes only from Telegram chat context (`chat.type`), never from
  `from_user.id`. Messages/edited messages from `group`/`supergroup` (and other
  non-private chats) are ignored. Callback queries from non-private chats are
  stopped and answered with `PRIVATE_CHAT_ONLY` (`show_alert=True`) so no
  spinner is left and no personal data is published.
- Fail closed: a callback without an accessible `message` (inline mode) or with
  an undeterminable chat is rejected. `InaccessibleMessage` carries `chat`, so
  it is checked like a regular message; private+inaccessible still works.
- Business rules, booking algorithms, FSM, keys, schema, migrations, scheduler
  and existing handlers are unchanged; only the update boundary was added.

## Confirmed architecture — TASK IV.1 (admin panel)

- Administrator identity comes only from the ``ADMIN_TELEGRAM_IDS`` environment
  variable, parsed by Pydantic Settings into ``frozenset[int]`` with
  ``NoDecode`` + ``BeforeValidator`` (comma-separated positive IDs, ``BIGINT``
  bound). Missing/blank means *no administrators* (fail closed); any invalid
  element rejects the whole configuration through the existing
  ``ConfigurationError`` path, which prints field names only.
- Authorization is checked twice and always from Telegram context
  (``event.from_user.id``), never from ``callback_data``:
  1. ``AdminOnlyMiddleware`` is registered as **inner** middleware on the admin
     router's ``callback_query`` and ``message`` observers. Inner (not outer) is
     deliberate: an outer middleware on a router also runs for updates that no
     handler matches, so it would answer every unrelated user message.
  2. Every public ``AdminService`` method calls ``_authorize()`` before doing
     anything else. A meta test asserts this for all public coroutine methods.
- ``AdminService.admin_ids`` is the single source of truth: ``build_dispatcher``
  derives the guard's ID set and the main-menu flag from it, and the admin
  router is always registered (with an empty set when there is no service).
- ``PrivateChatOnlyMiddleware`` stays unchanged and remains the only chat-type
  boundary; the admin panel does not duplicate it.
- Admin code is split like the client UI: ``barberbot/admin/`` (``errors``,
  ``service``, ``fsm``, ``callbacks``, ``keyboards``, ``texts``) plus
  ``barberbot/handlers/admin.py`` (guard + handlers + ``build_router``). The
  admin router is included after client routers and before the fallback.
- Business rules live in ``AdminService`` (authorization, runtime validation,
  pagination, conflict policy); SQL lives in the existing repositories
  (``CatalogRepository``, ``ScheduleRepository``, ``BookingRepository``). Write
  operations run in one ``session.begin()`` transaction; row locks
  (``with_for_update``) serialize service/barber edits and admin cancellations.
- Service snapshots are never rewritten; disabling a service or barber only
  hides it from new bookings, history stays. Nothing is physically deleted
  except ``barber_time_off`` rows (an exclusion, not a service/barber/booking).
- Schedule and time-off edits are rejected with ``AdminConflict`` (message lists
  the future confirmed bookings) when they would invalidate existing future
  bookings; the admin cancels those bookings first. Concurrent bookings cannot
  invalidate the check: `BookingService.create_booking()` locks the barber row
  (`SELECT … FOR UPDATE`) and then the service row **before** the final
  availability re-check + insert, in one transaction, and every admin
  schedule/time-off/barber-status edit holds the same barber row lock until its
  own commit. The PostgreSQL exclusion constraint stays the last line of defence
  against double booking.
- Admin cancellation intentionally bypasses the 2-hour client rule but still
  requires an explicit confirmation step; status is re-read under
  ``SELECT ... FOR UPDATE``, so repeated or parallel cancels yield exactly one
  success (``AdminBookingState`` afterwards).
- New barbers are created inactive: a barber without working hours must not
  appear in the client catalog.
- Main menu: ``main_menu_keyboard(admin=...)`` appends «⚙️ Админ-панель» only
  for an ID in the set; ``/start`` and «🏠 Главное меню» resolve the flag from
  ``admin_ids`` in ``workflow_data``.

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
