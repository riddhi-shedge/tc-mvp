-- Pipeline stage for the Deals board (Notion-style multi-view workspace).
-- Independent of `status` (open/archived): a deal is open AND at a stage.
alter table public.transactions
  add column if not exists stage text not null default 'new';
