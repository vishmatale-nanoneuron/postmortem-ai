-- Draft diffing: before this, re-drafting an incident silently overwrote
-- incident_postmortems' single row with no way to see what changed from
-- the previous draft -- adding evidence and re-drafting looked like a
-- mysterious full rewrite instead of a comparable, incremental change.
-- This table snapshots the previous draft's content immediately before
-- each overwrite (see api/v1/postmortems.py's draft_postmortem), so a
-- client can fetch the last snapshot and diff it against the new draft.
-- Append-only, same reasoning as payment_claim_events -- never updated or
-- deleted, a real history rather than a single mutable "previous" slot.
CREATE TABLE IF NOT EXISTS public.postmortem_draft_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id text NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
    summary text NOT NULL,
    root_cause text NOT NULL,
    detection text NOT NULL,
    resolution text NOT NULL,
    contributing_factors jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(contributing_factors) = 'array'),
    unsupported_claims_dropped integer NOT NULL DEFAULT 0 CHECK (unsupported_claims_dropped >= 0),
    superseded_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS postmortem_draft_history_incident_idx
    ON public.postmortem_draft_history (incident_id, superseded_at DESC);
