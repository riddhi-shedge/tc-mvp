-- Phase 3 (Prompt 3): the real ingestion agent.
--
-- The ingestion_inbox table is the lightweight queue (§13) between "document
-- detected" and "payload written": pending / needs_manual / confirmed / ignored.
-- Attachments are now retained (Phase 4 extraction needs the file) in a PRIVATE
-- storage bucket owned by ingestion; the row stores only the storage path.
-- Synthetic files only until the ZDR gate clears (§3).

alter type public.inbox_status add value if not exists 'needs_manual';
-- 'processing' = claimed by an in-flight confirm, so a concurrent confirm
-- can't duplicate master-side writes; released back to 'pending' on failure.
alter type public.inbox_status add value if not exists 'processing';

alter table public.ingestion_inbox
  add column if not exists detected_doc_type text,
  add column if not exists storage_path text,
  add column if not exists source text not null default 'email'
    constraint ingestion_inbox_source_check check (source in ('email', 'manual')),
  add column if not exists needs_manual_reason text;

-- Private bucket; storage.objects RLS denies anon/authenticated by default,
-- so only the backend's service role can read or write it.
insert into storage.buckets (id, name, public)
values ('ingestion-attachments', 'ingestion-attachments', false)
on conflict (id) do nothing;
