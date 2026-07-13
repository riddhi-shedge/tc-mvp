-- Phase 2 (Prompt 2): ingestion's own inbound queue.
--
-- This table belongs to part (a) — the ingestion agent — ONLY. The master
-- never reads or writes it (rules/architecture.md): ingestion consumes it and
-- talks to the master exclusively through validated Payloads over the API.
-- Phase 2 stores attachment METADATA only — no document content.

create type public.inbox_status as enum ('pending', 'confirmed', 'ignored');

create table public.ingestion_inbox (
  id uuid primary key default gen_random_uuid(),
  from_email text not null,
  to_email text not null,
  subject text,
  attachment_name text,
  attachment_content_type text,
  attachment_size integer,
  -- total attachments on the email; only the first's metadata is captured in
  -- Phase 2, so a count > 1 marks silently-dropped extras for the TC to see
  attachment_count integer not null default 0,
  status public.inbox_status not null default 'pending',
  -- cross-part reference by id only (no FK): the master owns transactions
  confirmed_transaction_id uuid,
  created_at timestamptz not null default now(),
  confirmed_at timestamptz
);

create index ingestion_inbox_status_idx on public.ingestion_inbox (status);

alter table public.ingestion_inbox enable row level security;
