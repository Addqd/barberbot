# BARBERBOT — PROJECT RULES

These project instructions supplement the user's global Pi `AGENTS.md`.
This repository is for a Telegram barbershop booking bot. Read `.agent/PROJECT.md`
before making project changes. For task work, maintain `.agent/TASK.md` as required
by the global workflow.

## Scope

- Follow only the user-approved MVP and verified local project configuration.
- Do not import architecture, requirements, dependencies, or UI decisions from other projects.
- Do not add payments, AI, loyalty programs, CRM, web frontend, deployment, or
  other features without explicit authorization.
- Start with minimal read-only discovery. Choose task-relevant installed skills,
  open each actual `SKILL.md` before editing, and revisit applicable skills at
  significant stages. Do not claim a skill was read unless it was opened.
- Use Context7 or primary documentation when a current framework/API detail
  materially affects implementation; verify tool availability first.

## Git/GitHub — absolute prohibition for Pi

Pi must **not perform ANY Git or GitHub operation**, including read-only commands
such as `git status`, `git diff`, or `git log`; nor may it inspect Git through
Git CLI, GitHub CLI, scripts, API, MCP, subagents, or alternative tools.
No commit, branch, push, pull, merge, PR creation, or history operations.
The user manages Git manually. If a global instruction suggests Git inspection,
this project-specific, explicitly agreed workflow takes precedence for Pi.

## Dependencies and environment

The user will initialize the Python project and install dependencies manually.
Pi must not install, update, remove, or introduce dependencies, create a virtual
environment, or modify machine configuration without explicit permission.
Keep secrets out of the repository, logs, screenshots, and reports. Use environment
variables for credentials; never commit a real bot token or database password.

## Implementation and verification

- Preserve the approved behavior, minimize scope, and write independently
  verifiable acceptance criteria in `.agent/TASK.md` before implementation edits.
- Validate Telegram updates, callback data, permissions, user inputs, and
  state transitions at runtime as relevant; type hints alone are insufficient.
- Protect booking integrity: overlapping slots and concurrent requests require
  database-enforced or transactionally verified safeguards when implemented.
- Test relevant behavior, including failure cases, and report actual evidence.
- This is initially a Telegram chat bot, **not a browser frontend**. Do not demand
  `pi-frontend-check` screenshots unless a real web UI is explicitly introduced.
  Verify Telegram conversations and inline-keyboard flows in their actual runtime.
- For each task, keep `.agent/TASK.md` accurate; leave unverified criteria unchecked.

## Collaboration workflow

1. User and ChatGPT agree on a task and a precise prompt for Pi.
2. Pi implements inside this workspace and runs applicable tests **without Git**.
3. User handles Git/PR manually and provides review material to ChatGPT.
4. ChatGPT reviews and, where needed, returns a ZIP of corrected project files.
5. User applies changes and verifies locally.

Do not claim success without actual verification. Report changed behavior, tests,
remaining unknowns, and blockers. Do not instruct Pi to perform Git steps.
