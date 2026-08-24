-- Core postmortem tables. The key structural guarantee lives in
-- incident_postmortems' CHECK constraint below: publishing requires a named
-- human approver, enforced by the database itself, not just application
-- code -- a bug in the API layer cannot silently publish an unapproved
-- postmortem.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.incident_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id text NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
    client_email text NOT NULL,
    occurred_at bigint NOT NULL,
    source text NOT NULL CHECK (source IN ('alert', 'log', 'deploy', 'metric', 'human_note', 'customer_report')),
    summary text NOT NULL CHECK (btrim(summary) <> ''),
    detail text,
    authorized_by text NOT NULL CHECK (btrim(authorized_by) <> ''),
    recorded_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS incident_evidence_incident_occurred_idx
    ON public.incident_evidence (incident_id, occurred_at);

CREATE TABLE IF NOT EXISTS public.incident_postmortems (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id text NOT NULL UNIQUE REFERENCES public.incidents(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'in_review', 'published')),
    summary text NOT NULL,
    root_cause text NOT NULL,
    detection text NOT NULL,
    resolution text NOT NULL,
    contributing_factors jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(contributing_factors) = 'array'),
    cited_evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(cited_evidence_ids) = 'array'),
    unsupported_claims_dropped integer NOT NULL DEFAULT 0 CHECK (unsupported_claims_dropped >= 0),
    generated_by text NOT NULL,
    approved_by text,
    approved_at bigint,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT published_requires_approver
        CHECK (status <> 'published' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.postmortem_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    postmortem_id uuid NOT NULL REFERENCES public.incident_postmortems(id) ON DELETE CASCADE,
    title text NOT NULL CHECK (btrim(title) <> ''),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    owner text NOT NULL CHECK (btrim(owner) <> ''),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'done', 'dropped')),
    evidence_id uuid REFERENCES public.incident_evidence(id) ON DELETE SET NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS postmortem_actions_postmortem_idx
    ON public.postmortem_actions (postmortem_id);
