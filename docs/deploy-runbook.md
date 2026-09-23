# Deploy Runbook — from localhost to a public URL

Companion to the /wizard readiness report (2026-09-11). Blockers B1–B3 are now
code; this file is the ordered checklist for the rest.

## 1. Backend host (any Procfile-style host or a VM)
- Start command: root `Procfile` or `backend/start.sh` (uvicorn, no --reload,
  binds 0.0.0.0:$PORT). Install `backend/requirements.txt` with Python 3.13.
- Provision EVERY var in `.env.example` (all of them exist for a reason; the
  app fails closed on missing ones). Non-obvious ones:
  - `APP_ENV=production` — hard-disables shared-secret auth (JWKS only).
  - `SUPABASE_JWT_SECRET` — must NOT be set in production.
  - `CA_RULES_VERIFIED=true` — rules were human-verified 2026-07-18.
  - `SYNTHETIC_ONLY=false` + `ZDR_CONFIRMED=true` — ONLY after zero-data-
    retention is actually confirmed with Anthropic (B5 — business step, not
    a flag flip).
  - `FRONTEND_ORIGIN=https://<your-frontend-host>` — CORS is single-origin.
  - Fresh strong values for `COMPLIANCE_SERVICE_TOKEN` and
    `POSTMARK_WEBHOOK_TOKEN` (do not reuse dev tokens).
- Optional host cron (daily compliance): `python -m app.compliance.scheduler`
  from the backend directory.

## 2. Frontend host (static)
- Build with `VITE_API_BASE=https://<backend-host>`, `VITE_SUPABASE_URL`,
  `VITE_SUPABASE_ANON_KEY` set — the production build now REFUSES to bake
  localhost fallbacks (vite.config.ts guard).
- Serve `frontend/dist/`. SPA fallback to index.html.

## 3. Database
- A fresh Supabase project reproduces the schema from
  `supabase/migrations/` (26 files, complete). Apply in order (supabase CLI
  `db push`, or the SQL editor). Enable MFA for the TC user.
- **Migration 26 (orgs) deploy ordering**: apply the migration FIRST, then
  deploy the matching backend right away. The migration backfills the demo org
  and enrolls existing non-party auth users, so new-code logins work the moment
  it lands — but the OLD backend cannot insert transactions/inbox rows once
  `org_id` is NOT NULL (creates fail, the webhook 5xxes and Postmark retries,
  nothing is lost). Keep the window between "apply" and "deploy" short.
- After migration 26, the calendar feed URL changes shape (per-org key):
  re-copy it from Deals → Calendar → feed URL and re-subscribe.

## 4. Post-deploy (B4)
- Postmark dashboard → inbound webhook URL:
  `https://<backend-host>/ingestion/webhooks/postmark` with the
  `X-Webhook-Token` header set to the new POSTMARK_WEBHOOK_TOKEN.
- Send a test email to the dedicated deal address; confirm an inbox item.
- Re-mint party invite links (old links embed the old origin in the URL the
  TC copied, not in the token — tokens keep working; the links just need the
  new frontend origin).

## 5. Verify (10 minutes)
- `GET /openapi.json` 200 over HTTPS; login w/ MFA works; CORS clean.
- Upload one synthetic PDF end-to-end (classify → confirm → deal).
- `evals/run.py` from a machine with the env (model stack sanity).
- Check the audit log recorded everything above.

## Should-fix backlog (non-blocking, from the report)
Rate limiting on public routes · error monitoring (5xx → Slack/webhook) ·
Maps/RentCast key referrer restrictions · daily compliance cron.
