-- P2: reply detection. When inbound mail references a message the SOR sent
-- (In-Reply-To / References ↔ messages.provider_message_id), the message is
-- marked answered — which auto-clears its follow-up reminder and removes the
-- "no reply" chase from the TC's decision queue. Only the fact and time of the
-- reply are recorded here; the reply's content stays in ingestion's inbox.

alter table public.messages
  add column if not exists replied_at timestamptz;
