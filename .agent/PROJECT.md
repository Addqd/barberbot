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
- Libraries, Python project initialization, DB and Git will be set up **manually
  later**; do not assume any are already configured in this repository.

## Explicit MVP exclusions

No online payments, loyalty system, AI assistant, full CRM, or additional business
locations unless the user changes the scope.

## Open decisions — do not invent

- Exact prices, durations, operating hours and timezone.
- Admin identities and authorization bootstrap.
- Reminder timing and delivery/retry policies.
- Final module layout and implementation conventions (choose during implementation).

## Agent and user workflow

- Global Pi rules + project-local `AGENTS.md`.
- `.agent/TASK.md` = local, temporary checklist; do not commit.
- Pi **never** performs Git or GitHub operations, including status/diff.
- User owns Git and installation; ChatGPT prepares prompts, reviews and ZIP fixes.

Update this file only for confirmed, durable architectural/product decisions.
