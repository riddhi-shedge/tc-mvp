-- Hardening (BUG-16): make document writes idempotent under retry.
--
-- The confirm route runs write_payload + derive_parties + derive_tasks as separate
-- steps. If a later step fails, ingestion releases the inbox item and the TC (or a
-- redelivery) retries the confirm — re-running write_payload, which re-inserted a
-- SECOND documents row for the same source document (external_ref = the source id).
--
-- A partial unique index on (transaction_id, external_ref) makes the duplicate
-- insert fail fast (23505); write_payload catches that and returns the already-
-- written payload instead (idempotent). NULL external_refs stay distinct.
--
-- IMPORTANT: `external_ref` is overloaded. write_payload sets it to the SOURCE
-- document id (what we want unique per deal), but add_party_document sets it to
-- 'party:<party_id>' as an ATTRIBUTION tag that legitimately repeats (a party may
-- upload several documents). The index therefore EXCLUDES 'party:%' refs — it
-- constrains only real source documents, and never rejects a party's Nth upload.
--
-- NOTE: only the source-document rows are constrained, so this cannot fail on (or
-- require de-duping) legitimate repeated party-upload rows.

create unique index if not exists documents_txn_external_ref_uidx
  on public.documents (transaction_id, external_ref)
  where external_ref is not null and external_ref not like 'party:%';
