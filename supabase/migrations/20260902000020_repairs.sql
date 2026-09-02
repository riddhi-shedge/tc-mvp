-- Repair-negotiation loop (Wave 1): tracked repair items. Created ONLY by the
-- TC (from a Request for Repairs' read facts — the click is the HITL), resolved
-- only by a human (repair.resolve is NEVER_BY_MACHINE in the authority matrix).
create table if not exists repairs (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references transactions(id) on delete cascade,
  description text not null,
  status text not null default 'open',           -- open | resolved
  source_document_id uuid references documents(id) on delete set null,
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);
alter table repairs enable row level security;
