-- Phase 6 (Prompt 6): real lender draft + approve/edit & send + audit.
--
-- Records the human approval on the message itself (approver + timestamp,
-- Rule 3) and the provider's message id on a real send. Follow-up reminders
-- link back to the message they chase. A reminder never sends anything.

alter table public.messages
  add column if not exists approved_by text,
  add column if not exists approved_at timestamptz,
  add column if not exists provider_message_id text;

alter table public.reminders
  add column if not exists message_id uuid references public.messages (id) on delete cascade;
