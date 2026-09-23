-- Multi-tenancy step 1 (technical-todo.md Track A1): organizations.
--
-- A TC business = one org. Deals and inbox items belong to an org; TC users
-- belong to an org via org_members. Child tables (parties, documents, ...)
-- inherit tenancy through their transaction — org_id lives ONLY on
-- transactions and ingestion_inbox (one ownership point, kept correct).
--
-- Backfill: every existing transaction/inbox row joins the demo org (fixed
-- UUID below), and every existing NON-party auth user (no app_metadata.
-- party_id) becomes an owner of it — so the deployed demo account keeps
-- working the moment this applies, before the new backend deploys.

create table public.orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  -- Local-part tag for plus-addressed inbound mail: deal+<inbound_key>@...
  -- routes to this org. Nullable: an org without a key gets no tagged inbound.
  inbound_key text unique,
  created_at timestamptz not null default now()
);
alter table public.orgs enable row level security;

create table public.org_members (
  org_id uuid not null references public.orgs (id) on delete cascade,
  -- auth.users id. No FK across schemas by design (Supabase guidance): auth
  -- user deletion is handled by the app, not a cascade.
  user_id uuid not null,
  role text not null default 'owner'
    constraint org_members_role_check check (role in ('owner', 'member')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index org_members_user_idx on public.org_members (user_id);
alter table public.org_members enable row level security;
-- No policies: deny-by-default for anon/authenticated. The backend reads these
-- with the service role; parties and the frontend anon key see nothing.

alter table public.transactions
  add column org_id uuid references public.orgs (id);
alter table public.ingestion_inbox
  add column org_id uuid references public.orgs (id);

-- The demo org (fixed id so env/config can reference it deterministically).
insert into public.orgs (id, name, inbound_key)
values ('00000000-0000-4000-8000-000000000001', 'Terra', 'terra');

update public.transactions
  set org_id = '00000000-0000-4000-8000-000000000001' where org_id is null;
update public.ingestion_inbox
  set org_id = '00000000-0000-4000-8000-000000000001' where org_id is null;

alter table public.transactions alter column org_id set not null;
alter table public.ingestion_inbox alter column org_id set not null;

create index transactions_org_idx on public.transactions (org_id);
create index ingestion_inbox_org_status_idx on public.ingestion_inbox (org_id, status);

-- Existing TC accounts (any auth user that is NOT a party session — party
-- users carry app_metadata.party_id) become owners of the demo org.
insert into public.org_members (org_id, user_id, role)
select '00000000-0000-4000-8000-000000000001', id, 'owner'
from auth.users
where coalesce(raw_app_meta_data ->> 'party_id', '') = ''
on conflict do nothing;
