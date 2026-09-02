-- Universal read: documents without a typed §5 extraction path (addenda, FHA
-- riders, HOA packets, emails, anything) get key facts + a summary from the
-- model at filing time. ADVISORY display data for the ledger only — facts
-- never create fields, parties, or deadlines.
alter table documents add column if not exists facts jsonb;
