-- P3: deal notes into the SOR. The TC's notes were localStorage-only — silently
-- losable browser state on a product positioned as the System of Record. Notes
-- are TC-authored working text scoped to a deal; parties never see them (no RLS
-- policies are granted, and the backend only serves them on the TC API).

create table public.deal_notes (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  body text not null check (length(body) > 0),
  color text not null default 'y',
  created_at timestamptz not null default now()
);

create index deal_notes_transaction_id_idx on public.deal_notes (transaction_id);

-- RLS on, no party policies: invisible to every invite-token session. The
-- backend reads/writes via the service role on TC-authenticated routes only.
alter table public.deal_notes enable row level security;
