-- Phase 1 (Prompt 1): the §10 SOR schema as a Supabase migration.
-- Source of truth: rules/data-model.md. Synthetic data only until ZDR clears.
--
-- Security baseline in this migration:
--   * audit_log is append-only, enforced by a trigger (not convention).
--   * RLS is ENABLED deny-by-default on every table. The backend uses the
--     service role (bypasses RLS); the anon key can read nothing. The four
--     §8 tier policies arrive in Phase 7.

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

create type public.document_status as enum ('pending', 'confirmed');
create type public.message_status as enum ('draft', 'approved', 'sent');
create type public.task_status as enum ('pending', 'in_progress', 'done', 'blocked');
-- The four §8 permission tiers a Party's role maps to.
create type public.permission_tier as enum
  ('operator', 'collaborator', 'receiving_end', 'email_participant');

-- ---------------------------------------------------------------------------
-- Core entities (§10)
-- ---------------------------------------------------------------------------

create table public.transactions (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'open',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.properties (
  id uuid primary key default gen_random_uuid(),
  -- one Property per Transaction
  transaction_id uuid not null unique references public.transactions (id) on delete cascade,
  address text not null,
  city text,
  -- Rule 4: California residential only — enforced by the DB, not just the API
  state text not null default 'CA' constraint properties_state_ca_check check (state = 'CA'),
  zip text,
  included_items text,
  excluded_items text,
  possession_notes text,
  created_at timestamptz not null default now()
);

create table public.parties (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  name text not null,
  company text,
  email text,
  phone text,
  -- free-form role (buyer, seller, lender, escrow, inspector_general,
  -- inspector_termite, inspector_roof, inspector_sewer, contractor, ...)
  role text not null,
  permission_tier public.permission_tier not null default 'email_participant',
  created_at timestamptz not null default now()
);

create table public.documents (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid references public.transactions (id) on delete cascade,
  external_ref text,  -- ingestion's document id from the Payload
  doc_type text,
  storage_path text,
  status public.document_status not null default 'pending',
  created_at timestamptz not null default now()
);

create table public.payloads (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  document_id uuid not null references public.documents (id) on delete cascade,
  party_id uuid references public.parties (id) on delete set null,
  raw jsonb not null,
  created_at timestamptz not null default now()
);

create table public.extracted_fields (
  id uuid primary key default gen_random_uuid(),
  payload_id uuid not null references public.payloads (id) on delete cascade,
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  name text not null check (length(name) > 0),
  value text not null,
  confidence numeric not null check (confidence >= 0 and confidence <= 1),
  confirmed boolean not null default false,
  deadline_driving boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.deadlines (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  name text not null,
  due_date date not null,
  source_field_id uuid references public.extracted_fields (id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.tasks (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  deadline_id uuid references public.deadlines (id) on delete set null,
  title text not null,
  status public.task_status not null default 'pending',
  -- a receiving-end party can own (and later mark done) its own task
  assigned_party_id uuid references public.parties (id) on delete set null,
  depends_on_task_id uuid references public.tasks (id) on delete set null,
  created_at timestamptz not null default now()
);

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  party_id uuid references public.parties (id) on delete set null,
  subject text,
  body text,
  -- Rule 3: draft -> approved -> sent; the sent transition requires a human
  -- Approval (no sending exists in Phase 1; the gate is built in Phase 6).
  status public.message_status not null default 'draft',
  created_at timestamptz not null default now(),
  sent_at timestamptz,
  -- symmetric: sent_at is set if and only if the message is sent
  constraint messages_sent_at_check check ((status = 'sent') = (sent_at is not null))
);

create table public.reminders (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  deadline_id uuid references public.deadlines (id) on delete set null,
  task_id uuid references public.tasks (id) on delete set null,
  remind_at timestamptz not null,
  note text,
  created_at timestamptz not null default now()
);

create table public.risk_flags (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  deadline_id uuid references public.deadlines (id) on delete set null,
  task_id uuid references public.tasks (id) on delete set null,
  severity text not null default 'warning',
  description text not null,
  resolved boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.approvals (
  id uuid primary key default gen_random_uuid(),
  transaction_id uuid not null references public.transactions (id) on delete cascade,
  message_id uuid references public.messages (id) on delete set null,
  item_type text not null default 'message',
  approved_by text not null,
  approved_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Audit log — append-only history of who did what and when.
-- No FK to transactions: the audit record must outlive every entity it
-- describes (deleting a transaction cascades its children, never its audit).
-- ---------------------------------------------------------------------------

create table public.audit_log (
  id bigint generated always as identity primary key,
  transaction_id uuid,
  actor text not null,
  action text not null,
  entity_type text not null,
  entity_id text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create function public.audit_log_block_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'audit_log is append-only: % not allowed', tg_op;
end;
$$;

create trigger audit_log_append_only
  before update or delete on public.audit_log
  for each row execute function public.audit_log_block_mutation();

-- ---------------------------------------------------------------------------
-- Indexes on the transaction_id lookups the API performs
-- ---------------------------------------------------------------------------

create index parties_transaction_id_idx on public.parties (transaction_id);
create index documents_transaction_id_idx on public.documents (transaction_id);
create index payloads_transaction_id_idx on public.payloads (transaction_id);
create index extracted_fields_transaction_id_idx on public.extracted_fields (transaction_id);
create index deadlines_transaction_id_idx on public.deadlines (transaction_id);
create index tasks_transaction_id_idx on public.tasks (transaction_id);
create index messages_transaction_id_idx on public.messages (transaction_id);
create index reminders_transaction_id_idx on public.reminders (transaction_id);
create index risk_flags_transaction_id_idx on public.risk_flags (transaction_id);
create index approvals_transaction_id_idx on public.approvals (transaction_id);
create index audit_log_transaction_id_idx on public.audit_log (transaction_id);

-- ---------------------------------------------------------------------------
-- RLS: enabled everywhere, deny-by-default (no policies yet — Phase 7 adds
-- the four-tier policies). Service role bypasses; anon/authenticated see nothing.
-- ---------------------------------------------------------------------------

alter table public.transactions enable row level security;
alter table public.properties enable row level security;
alter table public.parties enable row level security;
alter table public.documents enable row level security;
alter table public.payloads enable row level security;
alter table public.extracted_fields enable row level security;
alter table public.deadlines enable row level security;
alter table public.tasks enable row level security;
alter table public.messages enable row level security;
alter table public.reminders enable row level security;
alter table public.risk_flags enable row level security;
alter table public.approvals enable row level security;
alter table public.audit_log enable row level security;
