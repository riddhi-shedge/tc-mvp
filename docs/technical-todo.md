# Terra: Technical To-Do

*Written 2026-09-23 against the live codebase. The engineering work that turns Terra from a
single-user demo into a product a second customer can safely use. Companion to
`road-to-market.md` (which holds the business timeline); this doc is only the code.*

---

## Part 0 · Verified current state (why Terra is single-user today)

Checked in the code on 2026-09-23, not from memory:

1. **`transactions` has no owner.** `supabase/migrations/20260712000001_sor_core.sql` creates
   `transactions(id, status, created_at, updated_at)` and nothing else. No `org_id`, no
   `tc_id`. Every other table hangs off `transaction_id`, so nothing in the schema ties any
   deal to any user.
2. **Any logged-in user sees everything.** `require_tc` in `backend/app/common/auth.py` admits
   any Supabase-authenticated aal2 session in the project. There is no membership table and no
   check. Combined with (1) and unscoped queries in `app/master/repo.py`, a second Supabase
   user created in this project would see and edit every deal. Today the only protection is
   that signup is closed.
3. **The backend runs entirely on the service-role key** (bypasses RLS). The only RLS policies
   that exist are the receiving-end task policies in migration 7. Deny-by-default protects
   against the anon key, not against backend bugs.
4. **`ingestion_inbox` has no tenant column**, and `app/ingestion/routing.py` suggests a
   destination across *all* transactions. Inbound routing is per-deal (dedicated deal
   addresses) but there is no org boundary and no org-level catchall address.
5. **Send controls are global env vars**: `SEND_ALLOWLIST` and `POSTMARK_FROM_EMAIL` in
   `app/master/mailer.py` apply to the whole deployment, not per customer.
6. **No account lifecycle.** No signup flow, no password reset (`Login.tsx` says "contact your
   administrator"), no MFA recovery, no way to add a teammate.
7. **No rate limiting, no error monitoring** (no slowapi/Sentry anywhere in `app/`), CORS is a
   single `FRONTEND_ORIGIN`. CI exists (`.github/workflows/ci.yml`) and `/health` exists.
8. **Party access is already tenancy-safe by construction** — `require_party` binds the
   credential itself to one `party_id + transaction_id` (invite-token hash or
   `app_metadata`), so parties can never cross deals. This model survives multi-tenancy
   unchanged.

**Already solid, do not touch:** the five hard rules and their guards, append-only
`audit_log`, party credential binding, the §5 confirm gate, JWKS + production HS256 refusal,
the webhook fail-closed posture, evidence-first extraction, the eval harness.

---

## Track A · Multi-tenancy (the big one)

Goal: an `orgs` boundary where a TC business = one org, deals belong to orgs, users belong to
orgs, and nothing crosses. Do these steps in order; each is shippable.

### A1. Schema: orgs + membership + ownership (migration 26)

- [ ] `orgs (id uuid pk, name text not null, created_at)`
- [ ] `org_members (org_id fk, user_id uuid not null /* auth.users id */, role text not null
      default 'owner' check (role in ('owner','member')), created_at, unique(org_id, user_id))`
- [ ] `alter table transactions add column org_id uuid references orgs(id)` — nullable at
      first, then backfill and set `not null`:
      insert a "Terra Demo" org, assign every existing transaction to it, insert an
      `org_members` row for the demo TC's auth user id
- [ ] `alter table ingestion_inbox add column org_id uuid references orgs(id)` + same backfill
      (inbox rows have no `transaction_id` until confirm, so they need org directly)
- [ ] Indexes: `transactions(org_id)`, `ingestion_inbox(org_id, status)`,
      `org_members(user_id)`
- [ ] Child tables (parties, documents, payloads, extracted_fields, deadlines, tasks,
      messages, repairs, notices, closing_events, ops_items…) stay keyed by
      `transaction_id` only — they inherit tenancy through the transaction. Do NOT
      denormalize org_id onto all of them; one ownership point is easier to keep correct.

### A2. Auth: give `TCUser` an org

- [ ] Extend `TCUser` in `common/auth.py` with `org_id: str` and `org_role: str`
- [ ] In `require_tc`, after JWT verification, resolve membership from `org_members` by
      `sub` (user id). Fail closed with 403 "No organization" if absent. Cache lookups
      in-process for ~60s keyed by user id (same pattern as the JWKS cache) so it's one DB
      read per user per minute, not per request
- [ ] v1: single-org-per-user (take the first membership; unique-constraint later work adds
      an org switcher if ever needed)
- [ ] Tests: no membership → 403; membership → org_id populated; cache expiry honored

### A3. Repo scoping: one guard, used everywhere

- [ ] Add to `app/master/repo.py`: `assert_txn_in_org(transaction_id, org_id)` — fetch the
      transaction's `org_id`, raise 404 (not 403 — don't confirm existence) on mismatch.
      Every route that takes a transaction id calls it first
- [ ] `list_transactions` and every cross-deal read (dashboard, attention, portfolio
      aggregation, `/transactions/attention` bell) add `.eq("org_id", tc.org_id)`
- [ ] `create_transaction` stamps `org_id` from the caller
- [ ] Ingestion: `inbox_repo.py` queries all scoped by `org_id`; `routing.py`'s
      `suggest_transaction` already receives the TC's transaction list, which is now
      org-scoped upstream — verify, don't assume; sender-history map keyed per org
- [ ] Audit log rows gain the acting org in `actor` context (no schema change needed if
      recorded in the detail payload)
- [ ] **Tenancy conformance test** (the item that makes this stick): a pytest that seeds two
      orgs with one deal each, then walks every FastAPI route in the app's route table and
      asserts cross-org access returns 404/403. Any new route added later fails this test
      until it is explicitly scoped or marked exempt (webhook, health). This test is the
      moat against the classic "one forgotten endpoint" tenant leak

### A4. Inbound email per tenant

- [ ] Deal addresses already carry the deal → org comes from the transaction; stamp
      `org_id` on the inbox row at webhook time
- [ ] Add an org-level catchall address (`org-<short-id>@inbound…` via Postmark
      plus-addressing or additional inbound addresses) so unroutable mail still lands in the
      right org's Needs-Attention list instead of a global pool; parse the org from
      `OriginalRecipient` in `postmark_inbound_webhook`
- [ ] Mail to an address that maps to no org: absorb and log (current fail-closed behavior),
      never guess

### A5. Per-org send controls

- [ ] New table `org_settings (org_id pk/fk, send_mode text check in ('allowlist','open')
      default 'allowlist', send_allowlist jsonb default '[]', created_at, updated_at)`
- [ ] `mailer.py`: allowlist check reads org settings (env `SEND_ALLOWLIST` becomes a
      global-AND override for dev/demo deployments — an env-listed address restriction can
      only tighten, never loosen)
- [ ] Settings UI: a small org-settings screen (name, allowlist entries, members list)

### A6. Signup and teammate invites

- [ ] "Create organization" flow: new-user signup (Supabase signUp) → email verification →
      create org + owner membership → forced MFA enrollment (reuse the existing TOTP
      enrollment UI from `Login.tsx`) → land in empty workspace with a first-deal checklist
- [ ] "Invite teammate": owner enters email → Supabase admin invite (backend route, service
      role) → membership row created on accept → same MFA enrollment gate
- [ ] Keep a `SIGNUP_MODE=closed|invite|open` env so the public deployment can stay
      invite-only until pilots start

### A7. Storage scoping

- [ ] New uploads: prefix storage paths with `org/<org_id>/txn/<transaction_id>/…` in the
      ingestion bucket writes; keep old paths readable (map, don't migrate)
- [ ] Signed-URL generation routes call `assert_txn_in_org` before signing anything

### A8. Defense-in-depth RLS (after A1–A3 ship and pass)

- [ ] Phase 1 (cheap, now): DB-level tenancy policies mirroring the app checks —
      `transactions` policy `org_id in (select org_id from org_members where user_id =
      auth.uid())` for the `authenticated` role, child tables via `exists` against
      transactions. These cost nothing while the backend stays on service-role but make the
      posture honest the day any non-service-role path appears
- [ ] Phase 2 (later, larger): move TC *read* paths off service-role by forwarding the
      user's JWT to PostgREST so RLS actually enforces per-request. Writes can stay
      service-role behind the app guards. Do this before SOC 2, not before pilots

**Definition of done for Track A:** two orgs exist in the same deployment; each sees only its
own deals, inbox, documents, and sends; the conformance test walks every route; the demo org
still works untouched.

---

## Track B · Account lifecycle

- [ ] Password reset: `supabase.auth.resetPasswordForEmail` from a "Forgot password?" link on
      `Login.tsx`, plus a `/reset` screen that calls `updateUser`. Remove the "contact your
      administrator" line
- [ ] MFA recovery: decide and implement one of (a) recovery codes shown at enrollment, or
      (b) documented owner-initiated admin reset (backend route, owner role only, audited).
      (b) is a day of work and fine for pilots
- [ ] Email change flow (Supabase `updateUser` + re-verification)
- [ ] Per-user display name (replace the global `TC_NAME` env in drafts/status updates with a
      profile field; env stays as fallback)
- [ ] Session refresh handling in the frontend `api` layer: on 401, attempt
      `refreshSession()` once before bouncing to login (kills the stale-tab class of bugs
      seen in dev)

## Track C · Production hardening

- [ ] **Rate limiting**: slowapi (or a tiny middleware) — strict on `/webhooks/postmark`
      (per-IP), auth-adjacent routes, and every model-calling route (extract, classify,
      story, assistant); per-org quotas on model routes so one tenant can't drain the
      Anthropic budget
- [ ] **Sentry** (backend `sentry-sdk[fastapi]`, frontend `@sentry/react`) with PII scrubbing
      on: never send document content, field values, or email bodies — configure
      `send_default_pii=False` + a `before_send` filter, consistent with the logging
      discipline already in `main.py`
- [ ] Request IDs: middleware that stamps `X-Request-Id`, includes it in every log line and
      in error responses so a pilot bug report is greppable
- [ ] Daily compliance cron: Render Cron Job hitting a tokened backend route that runs the
      scheduler/attention recompute per org (the deploy-runbook should-fix item)
- [ ] Backups: verify Supabase PITR/backup tier on the hosted project and **run one restore
      drill into a scratch project**; write down the steps in `deploy-runbook.md`
- [ ] API key restrictions: Google Maps key locked to the frontend origins; RentCast key
      server-side only (verify it never appears in `VITE_*`)
- [ ] Invite-token hygiene: `pi_` tokens are permanent-until-revoked by design; add optional
      expiry (`expires_at` honored in `_resolve_invite`) + a "rotate link" button per party
      (re-mint already revokes); rate-limit invite resolution lookups
- [ ] Frontend security headers (Render static site headers): CSP, `X-Frame-Options: DENY`,
      `Referrer-Policy`, HSTS
- [ ] CI additions to `.github/workflows/ci.yml`: `pip-audit` + `npm audit --audit-level=high`
      + a secret scanner (gitleaks) as non-blocking-then-blocking steps
- [ ] Render paid tier for the backend before any pilot or live pitch (cold starts)

## Track D · Privacy, data rights, ZDR

- [ ] **ZDR/DPA with Anthropic** (business step, gates everything with real documents): once
      confirmed, set `ZDR_CONFIRMED=true`, retire `SYNTHETIC_ONLY` for pilot orgs. The
      `check_zdr_gate` plumbing already exists; do not touch it
- [ ] Org deletion endpoint (owner-only, confirmatory, audited): cascade-delete the org's
      transactions (schema already cascades) + purge its storage prefix + revoke invites.
      This is the CCPA/GDPR "delete my data" answer and the pilot-agreement exit clause
- [ ] Data export endpoint (owner-only): zip of documents + JSON of the SOR for an org —
      pilots will ask "can I get my files out?"
- [ ] Retention policy: decide and document (e.g. purge unconfirmed inbox items after 90
      days) — one cron task
- [ ] Privacy policy + ToS static pages, linked from `Login.tsx` footer

## Track E · Billing (build when a pilot converts, not before)

- [ ] Stripe: checkout + customer portal, `org_settings.stripe_customer_id`, plan column
- [ ] Metering: count "files" (transactions reaching confirmed-PA state) per org per month —
      this is the natural billing unit given per-file TC economics
- [ ] Gate: middleware maps org → plan state; past-due orgs go read-only, never deleted

## Track F · Model ops

- [ ] Usage metering: record model, input/output tokens, latency, org_id, purpose for every
      Anthropic call (extractor, classify_light, facts, verify, story, assistant) into a
      `model_usage` table — needed for per-org cost, pricing design, and spend alarms
- [ ] Spend alarm: daily cron sums yesterday's usage, emails you past a threshold (the credit
      exhaustion incidents will happen again; make them page you, not fail a pilot's upload)
- [ ] Centralize retry/backoff for Anthropic 429/529 in one place in `extractor.py`
- [ ] Evals: keep growing `backend/evals/golden.json` with every extraction bug found by
      pilots; add a weekly scheduled CI job that runs evals (paid calls, so scheduled, not
      per-PR)

## Track G · Product metrics (the pitch numbers)

- [ ] Minimal `events` table (org_id, name, properties jsonb, created_at) + a `track()`
      helper; instrument: inbox item received → classified → confirmed (time-to-file),
      extraction suggestions accepted vs corrected (acceptance rate), deadlines
      surfaced/acknowledged, weekly active orgs
- [ ] A tiny internal `/metrics` view (or a SQL notebook) that answers: files this month,
      median time-to-file, acceptance rate — the three numbers the deck needs

---

## Suggested order

| Step | Work | Size |
|------|------|------|
| 1 | Track C quick wins: Sentry, rate limiting, request IDs, key restrictions, CI audit steps, Render paid tier | ~2–3 days |
| 2 | Track A1–A3: orgs schema + auth org resolution + repo scoping + **conformance test** | ~1.5–2 weeks, the core |
| 3 | Track A4–A7: inbox org stamping, per-org send controls, signup/invites, storage prefixes | ~1 week |
| 4 | Track B: password reset, MFA recovery, profile | ~2–3 days |
| 5 | Track D: deletion/export endpoints, retention cron, policy pages (ZDR runs in parallel as a business step) | ~3–4 days |
| 6 | Track F + G: usage metering, spend alarm, events | ~2–3 days |
| 7 | Track A8 phase 1 RLS mirror policies | ~2 days |
| 8 | Track E billing — only when a pilot says yes to paying | ~1 week |

Everything above keeps the five hard rules intact; none of it touches extraction, date math,
or the approval gate. The conformance test in A3 is the single most important deliverable:
it converts "we believe tenancy is right" into "the route table proves it on every CI run."
