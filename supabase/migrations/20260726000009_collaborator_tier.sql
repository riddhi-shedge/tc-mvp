-- Collaborator tier (§8): buyer's/listing agent + broker get a READ-ONLY,
-- transaction-scoped view of the deal's timeline, tasks, parties, risks and
-- documents. Identity = a Supabase session whose admin-set app_metadata carries
-- {party_id, transaction_id, tier:'collaborator'}. Every policy is gated on
-- tier='collaborator', so a receiving-end token (tier='receiving_end') never
-- widens to these tables. Read-only (SELECT only): messages, audit_log,
-- payloads, extracted_fields, approvals, reminders stay deny-by-default.
grant select on public.transactions, public.properties, public.deadlines,
  public.parties, public.risk_flags, public.documents to authenticated;

create policy transactions_collab_select on public.transactions for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy properties_collab_select on public.properties for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy deadlines_collab_select on public.deadlines for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy tasks_collab_select on public.tasks for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy parties_collab_select on public.parties for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy risk_flags_collab_select on public.risk_flags for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
create policy documents_collab_select on public.documents for select to authenticated
  using (((select auth.jwt())->'app_metadata'->>'tier')='collaborator'
    and transaction_id = ((select auth.jwt())->'app_metadata'->>'transaction_id')::uuid);
