# tc-mvp

System of record (SOR) for California residential real-estate transaction
coordination. See `CLAUDE.md` for the five hard rules and architecture;
`docs/TC-Build-Requirements.md` is the authoritative build plan.

## Backend (Phase 1 — SOR core)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest            # unit tests (no network, synthetic only)
set -a; source ../.env; set +a
.venv/bin/python -m pytest            # + DB-integration tests against the dev project
.venv/bin/uvicorn app.main:app --reload
```

API (all routes require a Supabase TC session JWT with MFA/aal2):

- `POST /transactions` — TC creates a deal (HITL act).
- `POST /transactions/{id}/payloads` — the only deal-data write path (validated Payload).
- `GET /transactions/{id}` — full deal state, including the audit trail.

Schema lives in `supabase/migrations/` (applied to the dev project;
`supabase_migrations.schema_migrations` tracks versions).

## TC auth setup (one-time, Supabase dashboard)

1. Authentication → Sign In / Up: create the TC user (email + password).
2. Authentication → Multi-Factor: enable TOTP.
3. Enroll the TC in TOTP (frontend arrives in Phase 2; until then use the
   Supabase JS/Python client `mfa.enroll()` + `mfa.challenge()`/`verify()` from
   a scratch script) — the API rejects any session below `aal2`.
4. Put the project's legacy JWT secret in `.env` as `SUPABASE_JWT_SECRET`.
