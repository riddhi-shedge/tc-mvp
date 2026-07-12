# Code style — conventions

A living document. When a convention here causes repeated friction, propose a change
rather than silently diverging.

## General

- Small, single-purpose functions and modules. Favor clarity over cleverness.
- No secrets in code — everything sensitive comes from env vars (`.env`, gitignored). Never log a secret or any NPI.
- Match the surrounding code's naming and idiom when editing an existing file.

## Python (FastAPI backend)

- Python 3.10+. Full type hints on public functions.
- **Pydantic models for every boundary payload** — Payloads are validated, not trusted.
- Format/lint with `ruff` (and `black`-compatible formatting). Keep imports sorted.
- Tests with `pytest`; test files mirror the module under test.
- No cross-component database access (see `rules/architecture.md`) — a part reaches another part only through a Payload.

## TypeScript / React (frontend)

- `strict` mode on. No implicit `any`.
- Functional components + hooks. Keep components small; lift shared logic into hooks.
- The frontend uses the Supabase **anon** key only — its safety depends on row-level security being on. Never the service-role key.

## Commits & review

- Every non-trivial change goes through `code-reviewer` (fresh context) and, if it touches ingestion/messaging/data, `compliance-auditor` before shipping.
- Subagents are read-only reporters; the parent agent applies all fixes.
