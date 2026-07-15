-- Phase 5 fix: tag each compliance-generated row with the run that produced it,
-- so a re-run inserts the NEW timeline first and only then removes the prior
-- run's rows — old state stays visible until the new one fully lands (no
-- partial-empty window), and a mid-run failure compensates by deleting just the
-- new run's rows (mirrors write_payload's compensating pattern).

alter table public.deadlines add column if not exists compliance_run_id uuid;
alter table public.tasks add column if not exists compliance_run_id uuid;
alter table public.risk_flags add column if not exists compliance_run_id uuid;
alter table public.messages add column if not exists compliance_run_id uuid;
