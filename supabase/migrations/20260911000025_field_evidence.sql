-- Provenance v1 (#1): the verbatim quote each extracted field was read from
-- (produced by the evidence-first schema). Display-only.
alter table extracted_fields add column if not exists evidence text;
