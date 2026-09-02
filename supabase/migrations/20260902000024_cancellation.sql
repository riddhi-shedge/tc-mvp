-- Wave 4B: cancellation unwind. Records what the signed CC form says — the
-- effective date and the deposit DISPOSITION (a status word, never amounts or
-- movement: released_to_buyer | released_to_seller | disputed | n_a).
alter table transactions add column if not exists canceled_on date;
alter table transactions add column if not exists deposit_disposition text;
