-- Hardening (BUG-13): serialize compliance applies per deal.
--
-- `apply_compliance_result` inserts a new run's rows then deletes the prior run's.
-- Two overlapping applies for the SAME deal (the daily scheduler sweep racing a
-- manual "Build timeline" tap — both call the compliance-result endpoint) would
-- each delete the other's rows, leaving a torn or empty timeline.
--
-- This table is a per-transaction mutex: an apply acquires the row before it
-- writes and releases it after. A second concurrent apply can't acquire it and
-- backs off (the caller retries — applies are idempotent). `locked_at` lets a
-- stale lock (from a crashed apply) be reclaimed, so a non-graceful crash can't
-- wedge a deal's timeline forever.
--
-- The reconciliation itself (run_id insert-then-delete) is unchanged — this only
-- guarantees one apply runs at a time per deal, which is what makes it safe.

-- `lock_token` fences ownership: a reclaim/release only removes the row it owns,
-- so a slow (not crashed) holder whose lock was reclaimed can't later delete the
-- new holder's lock out from under it.
create table if not exists public.compliance_apply_lock (
  transaction_id uuid primary key,
  lock_token uuid not null,
  locked_at timestamptz not null default now()
);

alter table public.compliance_apply_lock enable row level security;
-- Backend (service role) only; no policy → anon/authenticated get nothing.
