-- Permanent invite links. The old links were ~1h Supabase session JWTs; these
-- are opaque tokens (pi_…) stored HASHED — a database leak does not leak live
-- links — and permanent until revoked. Minting a new link for a party revokes
-- the previous ones, so "re-invite" rotates the credential, matching the old
-- password-rotation semantics. Service-role only (RLS on, no policies).

create table public.party_invites (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  party_id uuid not null references public.parties (id) on delete cascade,
  tier text not null default 'receiving_end',
  token_hash text not null unique,   -- sha256 of the pi_ token; raw token never stored
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);

create index party_invites_party_id_idx on public.party_invites (party_id);
create index party_invites_token_hash_idx on public.party_invites (token_hash);

alter table public.party_invites enable row level security;
