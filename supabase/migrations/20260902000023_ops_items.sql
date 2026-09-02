-- Wave 3 slice A: ops lanes (HOA docs, home warranty, NHD report, utilities).
-- One generic order->done mini-chain per lane per deal; TC-advanced only.
create table if not exists ops_items (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references transactions(id) on delete cascade,
  lane text not null,                  -- hoa | warranty | nhd | utilities
  status text not null default 'ordered',  -- ordered | done
  ordered_on date,
  completed_on date,
  note text,
  created_at timestamptz not null default now(),
  unique (transaction_id, lane)
);
alter table ops_items enable row level security;
