-- Wave 2: closing-week choreography. Event-sourced closing state: each row is
-- a TC-confirmed step (Terra suggests from escrow emails, the human advances).
-- Ordered chain: docs_ordered -> cd_delivered -> signed -> funded -> recorded
-- -> keys_released. cd_delivered starts the federal TRID 3-business-day clock
-- (Saturdays count; Sundays + federal holidays don't — distinct from CA rules).
create table if not exists closing_events (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references transactions(id) on delete cascade,
  step text not null,                 -- docs_ordered | cd_delivered | signed | funded | recorded | keys_released
  occurred_on date not null,
  note text,
  created_at timestamptz not null default now(),
  unique (transaction_id, step)       -- each step happens once per deal
);
alter table closing_events enable row level security;
