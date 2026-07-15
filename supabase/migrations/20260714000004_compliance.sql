-- Phase 5 (Prompt 5): compliance/timeline service support.
--
-- Marks rows produced by the compliance service so a re-run can idempotently
-- REPLACE its prior output (delete generated_by='compliance' rows, re-insert)
-- without touching TC-authored rows. Also lets the service tie a deadline/task
-- to its stable compute key for dependency wiring.

alter table public.deadlines
  add column if not exists generated_by text,
  add column if not exists compute_key text;

alter table public.tasks
  add column if not exists generated_by text,
  add column if not exists compute_key text;

alter table public.risk_flags
  add column if not exists generated_by text,
  add column if not exists case_key text;

alter table public.reminders
  add column if not exists generated_by text;

alter table public.messages
  add column if not exists generated_by text;
