-- Track A5 + A6 (technical-todo.md): per-org send controls and teammate invites.
--
-- org_settings: who an org may email (Rule 3 stays: approve-and-send only;
-- this narrows WHERE an approved message may go, per workspace instead of one
-- global env var). No row = fail closed (env SEND_ALLOWLIST only, else refuse).
--
-- org_member_invites: opaque oi_ tokens stored HASHED (same pattern as
-- party_invites) — an owner mints a join link, the teammate accepts it with
-- their own authenticated (MFA'd) session, and membership is written then.

create table public.org_settings (
  org_id uuid primary key references public.orgs (id) on delete cascade,
  send_mode text not null default 'allowlist'
    constraint org_settings_mode_check check (send_mode in ('allowlist', 'open')),
  -- JSON array of lowercase email addresses approved messages may go to.
  send_allowlist jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.org_settings enable row level security;

create table public.org_member_invites (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.orgs (id) on delete cascade,
  email text not null,
  role text not null default 'member'
    constraint org_member_invites_role_check check (role in ('owner', 'member')),
  token_hash text not null unique,  -- sha256 of the oi_ token; raw never stored
  created_at timestamptz not null default now(),
  accepted_at timestamptz,
  accepted_by uuid,                 -- auth.users id that accepted
  revoked_at timestamptz
);
create index org_member_invites_org_idx on public.org_member_invites (org_id);
create index org_member_invites_token_hash_idx on public.org_member_invites (token_hash);
alter table public.org_member_invites enable row level security;
-- No policies on either table: service-role only, deny-by-default otherwise.

-- Members list needs emails (org_members stores auth user ids only). Denormalize
-- at membership time; backfill existing rows from auth.users.
alter table public.org_members add column email text;
update public.org_members m
  set email = u.email
  from auth.users u
  where u.id = m.user_id and m.email is null;
