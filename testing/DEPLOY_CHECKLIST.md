# Deploy checklist — apply the 3 hardening migrations BEFORE deploying current `main`

The BUG-13/17/16 fixes on `main` depend on schema that these migrations add. Apply
them to the hosted Supabase **first**, then deploy the code. All three are
idempotent (`if not exists`) and verified to parse as valid Postgres.

| Order | File | Adds |
|-------|------|------|
| 1 | `20260820000010_compliance_apply_lock.sql` | `compliance_apply_lock` table (per-deal apply mutex, BUG-13) |
| 2 | `20260820000011_inbox_claimed_at.sql` | `ingestion_inbox.claimed_at` column (stuck-processing reaper, BUG-17) |
| 3 | `20260820000012_documents_external_ref_unique.sql` | partial unique index on `documents(transaction_id, external_ref)` excluding `party:%` (retry idempotency, BUG-16) |

## Pre-apply check (only for #3)
Run this first — it should return **0 rows**. If it returns any, de-duplicate those
source documents before creating the index (party-upload rows are excluded and never a problem):

```sql
select transaction_id, external_ref, count(*)
from public.documents
where external_ref is not null and external_ref not like 'party:%'
group by 1, 2
having count(*) > 1;
```

## Apply
- **Supabase Dashboard → SQL Editor:** paste and run each file's contents in the order above; or
- **supabase CLI** (from a machine that has it): `supabase db push` (it applies pending migrations in filename order).

## Post-apply verification (each should return a row)
```sql
select to_regclass('public.compliance_apply_lock');                     -- table exists
select column_name from information_schema.columns
  where table_name = 'compliance_apply_lock' order by 1;                 -- locked_at, lock_token, transaction_id
select 1 from information_schema.columns
  where table_name = 'ingestion_inbox' and column_name = 'claimed_at';   -- claimed_at added
select indexname from pg_indexes
  where tablename = 'documents' and indexname = 'documents_txn_external_ref_uidx';  -- index created
```

## Then deploy
Deploy `main`. Smoke test: upload a doc → confirm → build timeline twice quickly
(the 2nd should 409 "in progress", not corrupt the timeline); re-send the same email
(should absorb as a duplicate, not create a 2nd deal).

## Notes
- `compliance_apply_lock` has RLS enabled with **no policy** — correct: the backend
  uses the service-role key (which bypasses RLS), and anon/authenticated get nothing.
- Rollback if ever needed: `drop index documents_txn_external_ref_uidx;`
  `alter table ingestion_inbox drop column claimed_at;` `drop table compliance_apply_lock;`
  (the app tolerates their absence only if you also roll the code back to before these fixes).
