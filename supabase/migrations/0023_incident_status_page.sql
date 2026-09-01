-- A live, public status page for an OPEN incident -- distinct from a
-- published postmortem's own public visibility (incident_postmortems.
-- is_public/slug), which only ever applies after the incident is over and
-- a postmortem has been drafted and approved. A customer checking "is it
-- down right now" needs this while the incident is still happening, often
-- before any postmortem exists at all.
ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false;
ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS public_slug text;

CREATE UNIQUE INDEX IF NOT EXISTS incidents_public_slug_idx
    ON public.incidents (public_slug) WHERE public_slug IS NOT NULL;

-- Curated public updates, deliberately NOT the same as incident_evidence.
-- Evidence entries can contain internal debugging detail, customer PII, or
-- raw log content never meant for a public page -- a status page shows
-- only what a human explicitly writes for public consumption, the same
-- "never auto-expose internal detail" stance this app already applies to
-- client_email on published postmortems.
CREATE TABLE IF NOT EXISTS public.incident_public_updates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id text NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
    message text NOT NULL CHECK (btrim(message) <> ''),
    posted_by text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS incident_public_updates_incident_idx
    ON public.incident_public_updates (incident_id, created_at DESC);
