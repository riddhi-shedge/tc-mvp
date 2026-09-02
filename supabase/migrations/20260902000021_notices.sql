-- NBP/NSP tracker (Wave 1): records that a Notice to Perform was SERVED (by
-- the agent, outside Terra — Terra tracks, never sends). Cure clock per
-- verified rules D2/D3 (docs/ca-rules-verification.md).
create table if not exists notices (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references transactions(id) on delete cascade,
  deadline_id uuid references deadlines(id) on delete set null,
  kind text not null default 'nbp',              -- nbp | nsp
  served_date date not null,
  cure_expires date not null,
  status text not null default 'open',           -- open | cured
  created_at timestamptz not null default now()
);
alter table notices enable row level security;
