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

API (all routes except the webhook require a Supabase TC session JWT with MFA/aal2):

- `POST /transactions` — TC creates a deal (HITL act). `GET /transactions` lists deals.
- `POST /transactions/{id}/payloads` — the only deal-data write path (validated Payload).
- `GET /transactions/{id}` — full deal state, including the audit trail.
- `POST /transactions/{id}/fields/confirm` — extraction-review confirm.
- `POST /transactions/{id}/timeline/stub` — hardcoded Phase 2 timeline (real CA rules: Phase 5).
- `POST /transactions/{id}/messages/draft-stub` — stub lender draft (real drafting: Phase 6).
- `POST /transactions/{id}/messages/{mid}/approve-and-send` — human approval; **fake** send (audit only).
- `POST /ingestion/webhooks/postmark` — inbound parse (dedicated deal address only;
  token via `X-Webhook-Token` header or `?token=`). Detects doc type, stores the
  attachment in the private `ingestion-attachments` bucket; unreadable → `needs_manual`.
- `GET /ingestion/inbox` — the queue (pending + needs-manual) with routing
  *suggestions* (transaction id in subject → sender history → address match).
- `POST /ingestion/inbox/{id}/confirm` — HITL "new deal or which existing?"
  (optional `doc_type` correction). For purchase agreements this runs the real
  extraction pipeline: pypdf pre-check → Claude (§5 fields with per-field
  confidence, whitelist-enforced). Pre-check/type/signature failures return a
  structured 422 (`manual_fields_required`) — pass `manual_fields` to enter
  values by hand (they land confirmed). `/dismiss` closes an item.
  **ZDR gate:** extraction refuses to run unless `SYNTHETIC_ONLY=true` or
  `ZDR_CONFIRMED=true` — no real client document until ZDR is confirmed.
- The timeline is BLOCKED (409, with the field names) until every
  deadline-driving §5 field on the deal is TC-confirmed.
- `POST /ingestion/manual-upload` — TC-authed fallback for unreadable emails/scans.

## Frontend (Phase 2 — walking-skeleton screens)

```bash
cd frontend
cp .env.example .env    # fill VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY (anon only!)
npm install
npm run dev             # http://localhost:5173 (backend on :8000)
```

Screens: TC login (password + TOTP MFA enroll/challenge to reach aal2) → Inbox
(HITL confirm) → Deal (extraction review → confirm → stub timeline → AI panel →
Approve & Send, which fakes the send and writes the audit trail).

Schema lives in `supabase/migrations/` (applied to the dev project;
`supabase_migrations.schema_migrations` tracks versions).

## TC auth setup (one-time, Supabase dashboard)

1. Authentication → Sign In / Up: create the TC user (email + password).
2. Authentication → Multi-Factor: enable TOTP.
3. Enroll the TC in TOTP (frontend arrives in Phase 2; until then use the
   Supabase JS/Python client `mfa.enroll()` + `mfa.challenge()`/`verify()` from
   a scratch script) — the API rejects any session below `aal2`.
4. Put the project's legacy JWT secret in `.env` as `SUPABASE_JWT_SECRET`.
