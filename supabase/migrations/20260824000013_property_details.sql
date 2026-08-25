-- Personalized party workspaces: cache address enrichment on the property.
--
-- The buyer/agent/appraiser property card shows real house facts + a photo pulled
-- from the address (RentCast + Google Street View). We cache the result so we
-- don't re-hit those APIs on every party page load (RentCast free tier is small):
--   details    — { facts: {beds,baths,sqft,…}, photo_url, deep_links }
--   enriched_at — when we last fetched (null ⇒ never; re-enrich when no useful data)
-- Public-record + street imagery only — no document content, no Rule-5 data.

alter table public.properties
  add column if not exists details jsonb,
  add column if not exists enriched_at timestamptz;

-- Public bucket for the Street View exterior photo (public-record imagery; the
-- party view is unauthenticated-by-invite-token, so a public URL is simplest).
insert into storage.buckets (id, name, public)
values ('property-media', 'property-media', true)
on conflict (id) do nothing;
