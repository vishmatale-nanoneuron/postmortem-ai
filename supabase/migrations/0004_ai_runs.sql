-- Real monitoring surface for AI drafting calls: one row per /draft call,
-- success or failure, queryable directly (not a dashboard that doesn't
-- exist yet). Also carries prompt_version so incident_postmortems' own
-- prompt_version column (added below) can be cross-checked against actual
-- call history.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.ai_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id text NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
    provider text NOT NULL,
    model text NOT NULL,
    prompt_version text NOT NULL,
    input_chars integer NOT NULL CHECK (input_chars >= 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
    latency_ms integer NOT NULL CHECK (latency_ms >= 0),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    error_type text,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS ai_runs_incident_idx ON public.ai_runs (incident_id);
CREATE INDEX IF NOT EXISTS ai_runs_created_at_idx ON public.ai_runs (created_at);

-- Traceability: which prompt version drafted this postmortem. Nullable-free
-- (backfilled to 'v1' for any pre-existing row, since that's the only
-- prompt version that has ever existed) rather than nullable, so every row
-- always answers "which prompt made this."
ALTER TABLE public.incident_postmortems ADD COLUMN IF NOT EXISTS prompt_version text;
UPDATE public.incident_postmortems SET prompt_version = 'v1' WHERE prompt_version IS NULL;
ALTER TABLE public.incident_postmortems ALTER COLUMN prompt_version SET NOT NULL;
