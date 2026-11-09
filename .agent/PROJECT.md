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
