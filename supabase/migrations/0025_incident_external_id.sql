-- Lets an incident remember an external system's own id for it -- needed
-- for the new PagerDuty webhook adapter (webhooks.py): PagerDuty's
-- incident.triggered / incident.acknowledged / incident.resolved events for
-- one PagerDuty incident all carry the *same* event.data.id across its
-- lifecycle, but PagerDuty has no way to be told this app's own incident id
-- in return (unlike the existing generic webhook, where the caller is
-- expected to pass incident_id back itself). Storing PagerDuty's id lets a
-- later "resolved" event find the incident that a "triggered" event already
-- created, instead of creating a duplicate.
--
-- Nullable and unscoped by source on purpose: the only two writers today
-- (PagerDuty adapter, and whatever comes next that has the same "I can't
-- ask the caller to remember my id" problem) always look this up scoped by
-- client_email AND status='open' first, so a single text column is enough
-- without a separate source column -- add one only if a second such
-- integration is ever built and the two could plausibly collide.
ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS external_id text;

CREATE INDEX IF NOT EXISTS incidents_external_id_idx
    ON public.incidents (client_email, external_id)
    WHERE external_id IS NOT NULL;
