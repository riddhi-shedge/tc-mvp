-- Hardening (BUG-17): reclaim a stuck 'processing' inbox item.
--
-- `claim()` flips an inbox item pending -> processing before the master write, so
-- a concurrent confirm can't duplicate side effects. But a non-graceful crash
-- between claim() and release()/mark_confirmed() leaves the item stranded in
-- 'processing' — it drops out of list_open() (pending/needs_manual only) and the
-- TC never sees it again.
--
-- `claimed_at` records when the item was claimed so a stale claim (from a crashed
-- confirm) can be reclaimed back to 'pending' and resurface in the queue.

alter table public.ingestion_inbox
  add column if not exists claimed_at timestamptz;
