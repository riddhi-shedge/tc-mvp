# Staging deployment (Render) — SYNTHETIC ONLY

Stand up a hosted, demo-able tc-mvp on **synthetic data only**. The safety gates
stay closed the whole time, so staging cannot process real client data or send
real email:

- `SYNTHETIC_ONLY=true` — the ZDR gate blocks real documents (extraction/drafting
  hard-stop on real data).
- `SEND_ENABLED=false` — no outbound email leaves the system.
- `CA_RULES_VERIFIED=true` — staging exercises the real (verified 6/26) date math
  on synthetic deals. This is safe: it only affects deadline computation, not data
  handling.

Supabase is already managed and external — staging points at the same project (or
make a separate Supabase project for true isolation; recommended before real data).

## What deploys (render.yaml blueprint)

| Service | Type | What it is |
|---|---|---|
| `tc-mvp-api` | Docker web | FastAPI API + Postmark inbound webhook (`/health` health check) |
| `tc-mvp-frontend` | Static site | the Vite build, SPA-rewritten to `index.html` |
| `tc-mvp-scheduler` | Docker cron | daily `python -m app.compliance.scheduler` (talks to the API only) |

## One-time setup

1. **Push to GitHub** (CI runs on push: backend `ruff` + `pytest`, frontend build).
2. In Render: **New → Blueprint**, point it at this repo. Render reads `render.yaml`
   and creates the three services.
3. **Set the secrets** (marked `sync: false`) in each service's *Environment* tab —
   copy the non-secret-appropriate values from your local `.env`. Do NOT commit them.
   - `tc-mvp-api`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`,
     `ANTHROPIC_API_KEY`, `POSTMARK_SERVER_TOKEN`, `POSTMARK_FROM_EMAIL`,
     `POSTMARK_WEBHOOK_TOKEN`, `COMPLIANCE_SERVICE_TOKEN`, `FRONTEND_ORIGIN`.
   - `tc-mvp-frontend`: `VITE_API_BASE` = the `tc-mvp-api` URL.
   - `tc-mvp-scheduler`: `MASTER_API_BASE` = the `tc-mvp-api` URL,
     `COMPLIANCE_SERVICE_TOKEN` (same value as the API's).
4. After the first deploy, fill the two URL-dependent vars now that URLs exist:
   `FRONTEND_ORIGIN` (API, = frontend URL, for CORS), `VITE_API_BASE` and
   `MASTER_API_BASE` (= API URL), then redeploy.
5. **Point Postmark inbound** at `https://<tc-mvp-api-url>/ingestion/webhooks/postmark?token=<POSTMARK_WEBHOOK_TOKEN>`
   (the token guards the webhook). Send a synthetic PA to your inbound address to
   drive the flow.

## Verify

- `GET https://<api-url>/health` → `{"status":"ok"}`.
- Log in (MFA) and run a synthetic deal through the screens (same slice as
  `tests/test_end_to_end.py`).
- Confirm posture on the API shell: `python -m scripts.zdr_preflight` → synthetic-only.

## Local hosted-style staging (no Render)

```
docker compose up --build      # API :8000, frontend :5173 — both synthetic-only
```

## Going from staging → production (later, gated)

Do NOT reuse this blueprint for real data as-is. Before production:
- Flip gates only after the external clearances: `ZDR_CONFIRMED=true` +
  `SYNTHETIC_ONLY=false` (ZDR agreement), `SEND_ENABLED=true` + `SEND_ALLOWLIST`
  (Postmark approval), C.A.R. IP opinion.
- Use a **separate** Supabase project + a paid Render plan (the free plan sleeps),
  a custom domain + DKIM/SPF/DMARC, document encryption-at-rest, backups,
  monitoring, and a retention/incident-response plan (see §20 of the build doc).
