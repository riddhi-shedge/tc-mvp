-- Batch-upload classify: when a document falls outside the known types, the
-- model returns a free-text best guess ("AVID — Agent Visual Inspection
-- Disclosure"). Advisory only — shown to the TC, who still decides the filing.
alter table ingestion_inbox add column if not exists doc_guess text;
