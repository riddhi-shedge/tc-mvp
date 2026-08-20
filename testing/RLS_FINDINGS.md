# Authorization / Multi-Tenant Isolation Audit — TC-MVP Backend

**Scope:** party-scoped authorization and cross-deal isolation for backend-mediated (FastAPI) requests.
**Date:** 2026-08-17. Method: static read of source + migrations + tests. DB-integration tests not executed (no Supabase env; pytest not installed locally).

---

## TL;DR VERDICT

**Cross-party / cross-deal data isolation IS enforced in application code for backend-mediated requests.** The backend connects with the Supabase **service role, which bypasses Postgres RLS** (`backend/app/master/repo.py:653`, `backend/app/ingestion/inbox_repo.py:115`), so the RLS migrations are **not** the control for the API. The three non-TC ("party") routes derive `transaction_id` **and** `party_id` exclusively from the signed, admin-set JWT (`app_metadata`), never from client input, and the repo layer double-scopes every query by `transaction_id`. No IDOR was found on the party attack surface.

The residual issues are (a) an unproven DB-side RLS control that only matters if a party uses its real Supabase token **directly** against PostgREST, (b) a tier-confusion write gap where a "read-only" collaborator can still write through the backend, and (c) no invite-token revocation. None of these breach cross-tenant isolation; they are integrity/defense-in-depth gaps.

---

## CONTEXT VERIFIED: service role bypasses RLS

- Backend Supabase clients are built with `SUPABASE_SERVICE_ROLE_KEY`: `repo.py:653`, `inbox_repo.py:115`, and the issuer admin client `party_access.py:58,79`.
- The service role bypasses RLS by design. Therefore **for any request that flows through the backend, RLS enforces nothing** — authorization must be in app code. The RLS migrations (below) only bind a caller using the `authenticated` role directly against Supabase/PostgREST (i.e., a party using its issued session token *outside* the backend). This is even documented in the migration header: `20260715000007_rls_tiers.sql:4-5` ("Operator (TC): full access — via the backend SERVICE ROLE, which bypasses RLS").

---

## 1. Intended RLS tiers (from migrations)

`supabase/migrations/20260715000007_rls_tiers.sql` and `20260726000009_collaborator_tier.sql`:

- **Operator / TC** — full access via service role; no policy needed (RLS bypassed).
- **receiving_end** (inspector/appraiser/contractor) — identity = Supabase session with admin-set `app_metadata.party_id`. May `SELECT` only tasks where `assigned_party_id = jwt party_id`, and may `UPDATE` only the `status` column of its own task (`revoke update ... ; grant update (status)`; policies `tasks_receiving_end_select`, `tasks_receiving_end_update`, lines 23-40). Everything else deny-by-default.
- **collaborator** (buyer/listing agent, broker) — identity carries `app_metadata {party_id, transaction_id, tier:'collaborator'}`. Read-only (`SELECT` only) transaction-scoped view of `transactions, properties, deadlines, tasks, parties, risk_flags, documents`, every policy gated on `tier='collaborator' AND ...transaction_id = jwt transaction_id` (migration 9, lines 11-31). `messages, audit_log, payloads, extracted_fields, approvals, reminders` stay deny-by-default.
- **email_participant** — out of MVP scope; no policy → deny-by-default (gets no DB credential at all; see `_invite_tier`, `routes.py:528-535`).

These policies are coherent and correctly written (native-uuid compare, `(select auth.jwt())` scalar subselect). **But they only guard direct PostgREST access, not the API.**

---

## 2. Auth mechanisms (`backend/app/common/auth.py`)

- **TC** — `require_tc` (`auth.py:158-182`): verifies Supabase JWT (HS256 via `SUPABASE_JWT_SECRET` in dev — banned in production, `auth.py:99-102`; else JWKS ES256/RS256), requires `role=authenticated`, **rejects any token carrying `app_metadata.party_id`** (defense-in-depth, `auth.py:174-176`), and requires `aal=aal2` (MFA) unless `REQUIRE_MFA=false`.
- **Scoped party** — `require_party` (`auth.py:130-155`): accepts any authenticated token whose `app_metadata` has both `party_id` and `transaction_id`. **Crucially, `transaction_id` and `party_id` are taken from the signed token, never the client** (`auth.py:147-154`). `tier` defaults to `receiving_end`.
- **Service token** — `require_compliance_service` (`routes.py:107-118`): constant-time compare against `COMPLIANCE_SERVICE_TOKEN`; fails closed (503) when unset. Same pattern for the Postmark inbound webhook token.
- Token forgery of `app_metadata` is not possible: only the service role (`admin.auth.admin.create_user/update_user_by_id`, `party_access.py:88-105`) sets `app_metadata`. A self-service anon signup carries no `party_id` → `require_party` 401s, `require_tc` MFA-gates.

---

## 3. Non-TC attack surface — IDOR analysis

Only three routes accept a party token (`require_party`). **None take an id from the URL/body that is used for authorization** — the ids come from the token:

| Route | file:line | Isolation check | IDOR? |
|---|---|---|---|
| `GET /party/workspace` | `routes.py:1121-1171` | `state = get_full_state(party.transaction_id)`; `me` must be in parties (403 else); tasks filtered `assigned_party_id == party.party_id`; docs filtered `external_ref == party:{party_id}` | **No** |
| `POST /party/tasks/{task_id}/status` | `routes.py:1178-1197` | loads `party.transaction_id`; requires `task.assigned_party_id == party.party_id` (404 else); repo `set_task_status` additionally `.eq("transaction_id", …)` (`repo.py:1758-1765`) | **No** |
| `POST /party/documents` | `routes.py:1206-1224` | `transaction_id` + `party_id` from token; storage path namespaced `{txn}/party/{party}/…` (`repo.py:1910`) | **No** |

`task_id` in the status route is the only client-supplied id, and it is validated against **both** the caller's transaction and their own `party_id` before any write; the repo write is also transaction-scoped. **A party cannot read or modify another party's task or another deal's data.** CONFIRMED, covered by non-skipped unit tests `test_party_workspace.py:42-92` (incl. `test_party_cannot_touch_a_task_not_theirs`, `test_party_token_rejected_by_tc_api`).

TC-only issuance routes (`create_party_access_token` `routes.py:538-571`, `email_party_invite` `:580-648`, `update_party` `:499-519`) validate `repo.get_party(party_id, transaction_id)` so a party from another deal is 404 (`test_access_token.py:79`). `document_signed_url` (`repo.py:1876-1892`) and `write_payload` (`routes.py:1244-1277`, `party_belongs_to_transaction`) are also transaction-scoped. No IDOR.

---

## FINDINGS

### F1 — RLS is not the control for the API; only proven by skipped tests — CONFIRMED, P2 (gap/assurance)
The DB-side tier isolation (the safety net if a party ever uses its **real** Supabase session token directly against PostgREST, bypassing the backend) is exercised **only** by tests that are entirely skipped in CI: `test_rls_permissions.py` (6 tests), `test_rls_collaborator.py` (4), `test_db_integration.py` (10), `test_auth_jwks.py` (2) — all gated by `pytest.mark.skipif(not SUPABASE_URL/SERVICE_ROLE/ANON)` (`test_rls_permissions.py:25-34`, `test_rls_collaborator.py:22-30`, `test_db_integration.py:19-22`). Party access tokens **are** genuine Supabase sessions (`party_access.py:107-113`) and can be replayed directly against PostgREST, at which point RLS is the ONLY control. If a policy regresses (e.g., a future `grant`/policy edit), nothing in CI catches it. **Exploit path:** issue a receiving_end token, call `{SUPABASE_URL}/rest/v1/parties?select=*` directly with it; correctness depends entirely on unverified RLS. **Recommendation:** run the RLS suite against an ephemeral Supabase in CI, or explicitly document that party tokens must never be given PostgREST reach.

### F2 — Tier confusion on write routes: read-only collaborator can write via backend — CONFIRMED, P2
`require_party` does not distinguish `receiving_end` from `collaborator` (`auth.py:130-155`), and neither write route checks `party.tier`:
- `POST /party/documents` (`routes.py:1206-1224`) has **no tier gate and no assignment check** — any party token, including a `collaborator` one, can upload a document into the deal.
- `POST /party/tasks/{task_id}/status` (`routes.py:1178-1197`) would let a collaborator mark a task done if one were assigned to them.

Per design, a collaborator is **read-only** (migration 9 grants `SELECT` only; no `INSERT`/`UPDATE`). Because the backend uses the service role and bypasses RLS, that read-only contract is **not** enforced on the API path. **Exploit:** TC issues an agent a `collaborator` invite (`_invite_tier`, `routes.py:533`); the agent calls `POST /party/documents` with their bearer and writes an arbitrary file/`doc_type` into the deal. **Blast radius is limited to the collaborator's OWN transaction** (transaction_id from token) — this is a tier/integrity violation, **not** cross-tenant leakage. **Fix direction:** gate the two write routes on `party.tier == "receiving_end"` (and, for documents, ideally on having an assigned task). `doc_type` is also unvalidated free text.

### F3 — Invite-token lifecycle: no revocation; reusable within TTL — CONFIRMED, P3
`party_access.py:50-54` explicitly documents that reissuing rotates the auth user's password but, JWTs being stateless, **does not revoke an already-issued access token before expiry**. 
- **Expiry:** relies on the default Supabase session TTL; `_decode` verifies `exp`/`aud` (`auth.py:103-111`), so expired tokens are rejected.
- **Revocation:** none. A leaked/compromised invite token is valid until it expires; there is no jti/denylist. 
- **Replay:** the token is a plain reusable bearer within its TTL (no nonce).
- **Scope-escalation:** NOT possible — `app_metadata` (party_id/transaction_id/tier) is admin-set via the service role only; a party cannot alter its own claims, and a plain signup yields no `party_id`. So a party cannot widen from `receiving_end` to `collaborator` or hop deals.

**Recommendation:** keep TTL short; if stronger control is needed, add a per-token version/`jti` checked against a revocation table on `require_party`.

### F4 — Compliance service token is a single shared secret across all deals — THEORETICAL, P3
`require_compliance_service` (`routes.py:107-118`) guards `compliance-state`, `compliance-result`, and `compliance-active` with one shared `COMPLIANCE_SERVICE_TOKEN`. `transaction_id` comes from the URL, so a holder can read/apply compliance for **any** deal by enumeration (`routes.py:972-1044`). This is a machine-to-machine trust boundary, not a per-tenant one, and it fails closed when unconfigured — but if the secret leaks it grants full cross-deal compliance read/write. Keep it out of any browser/party context; rotate on suspicion.

---

## What is solid
- Party routes derive all authorization ids from the signed token; repo methods `set_task_status`/`document_signed_url`/`add_party_document` all re-scope by `transaction_id` (defense in depth): `repo.py:1758-1765, 1879-1885, 1910`.
- `require_tc` positively rejects party tokens and enforces aal2; dev HS256 secret banned in production (`auth.py:99-102, 174-180`).
- App-code isolation IS covered by non-skipped unit tests (`test_party_workspace.py`, `test_access_token.py`) using a fake repo.

## Bottom line
For backend-mediated requests, cross-party and cross-deal isolation **is** correctly enforced in application code — the service-role/RLS-bypass concern does not translate into a data-isolation breach on the API. The real gaps are assurance (RLS proven only by skipped tests, F1) and tier integrity (collaborator can write, F2), plus no token revocation (F3). No P0/P1 cross-tenant IDOR found.
