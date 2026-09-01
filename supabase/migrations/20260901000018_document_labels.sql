-- Display label for documents filed as 'other': Terra's content-level guess
-- ("AVID — Agent Visual Inspection Disclosure") or the TC's own words, so the
-- Documents tab never shows a wall of indistinguishable "Other" cards.
alter table documents add column if not exists label text;
