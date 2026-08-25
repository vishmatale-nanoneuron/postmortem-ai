-- Opt-in public postmortem pages: a client can publish a postmortem to a
-- real, SEO-friendly public URL (/postmortems/[slug]) for transparency/
-- marketing. Private (is_public=false) by default -- nothing becomes
-- public without an explicit per-postmortem action from its owner.
ALTER TABLE public.incident_postmortems ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false;
ALTER TABLE public.incident_postmortems ADD COLUMN IF NOT EXISTS slug text;

CREATE UNIQUE INDEX IF NOT EXISTS incident_postmortems_slug_idx ON public.incident_postmortems (slug)
    WHERE slug IS NOT NULL;
