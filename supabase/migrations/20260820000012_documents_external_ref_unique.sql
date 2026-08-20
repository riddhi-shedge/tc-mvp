-- Hardening (BUG-16): make document writes idempotent under retry.
--
-- The confirm route runs write_payload + derive_parties + derive_tasks as separate
-- steps. If a later step fails, ingestion releases the inbox item and the TC (or a
-- redelivery) retries the confirm — re-running write_payload, which re-inserted a
-- SECOND documents row for the same source document (external_ref = the source id).
--
-- A partial unique index on (transaction_id, external_ref) makes the duplicate
-- insert fail fast (23505); write_payload catches that and returns the already-
-- written payload instead (idempotent). NULL external_refs stay distinct (a doc
-- with no source id is never deduped), which is why this is a PARTIAL index.
--
-- NOTE: if the pre-fix bug already produced duplicate (transaction_id, external_ref)
-- rows in a given database, de-duplicate them before applying this index.

create unique index if not exists documents_txn_external_ref_uidx
  on public.documents (transaction_id, external_ref)
  where external_ref is not null;
