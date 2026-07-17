-- Phase 7 (Prompt 7): §8 permission tiers enforced in the DATABASE via RLS.
--
-- Tiers (§8):
--   * Operator (TC): full access — via the backend SERVICE ROLE, which bypasses
--     RLS. Unchanged; no policy needed.
--   * Receiving-end (inspector/appraiser/contractor): may mark exactly their OWN
--     task done and see nothing else. Enforced here.
--   * Collaborator / Email-participant: out of MVP scope (§8) — no policy, so
--     deny-by-default.
--
-- Identity: a receiving-end party presents a genuine Supabase-issued session
-- (role=authenticated) whose admin-set `app_metadata.party_id` names the party.
-- The project signs with rotating asymmetric keys, so the claim lives in
-- app_metadata (admin-only — a party can't forge it) rather than a hand-minted
-- top-level claim. RLS keys off auth.jwt()->'app_metadata'->>'party_id'. Every
-- table without an `authenticated` policy stays deny-by-default, so the token
-- reads nothing but its own task.

-- The receiving-end party may only change task STATUS, never title/assignment/
-- dependencies. Column-level grant enforces this; the row policy scopes it to
-- their own task. (Only receiving-end tokens use the `authenticated` role for
-- table access — the TC uses the service role, the frontend anon key is auth-only.)
revoke update on public.tasks from authenticated;
grant select on public.tasks to authenticated;
grant update (status) on public.tasks to authenticated;

-- The claim is compared as a native uuid, and auth.jwt() is wrapped in a scalar
-- subselect — Supabase's documented RLS pattern, which also lets the planner
-- evaluate the claim once per statement instead of once per row.
--
-- SELECT: a receiving-end party sees only tasks assigned to them.
create policy tasks_receiving_end_select on public.tasks
  for select to authenticated
  using (assigned_party_id = ((select auth.jwt()) -> 'app_metadata' ->> 'party_id')::uuid);

-- UPDATE: only their own task, and it must stay theirs (can't reassign away).
create policy tasks_receiving_end_update on public.tasks
  for update to authenticated
  using (assigned_party_id = ((select auth.jwt()) -> 'app_metadata' ->> 'party_id')::uuid)
  with check (assigned_party_id = ((select auth.jwt()) -> 'app_metadata' ->> 'party_id')::uuid);

-- No policies are added for `authenticated` on any other table: transactions,
-- properties, parties, documents, payloads, extracted_fields, deadlines,
-- messages, reminders, risk_flags, approvals, audit_log, ingestion_inbox all
-- remain deny-by-default for a receiving-end token (RLS already enabled on each).
