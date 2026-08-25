-- Generic per-account rate limiting for authenticated actions beyond
-- login (login_attempts stays login-specific: email/ip/succeeded columns
-- don't fit a general action log). Real gap being closed: create_incident
-- and draft_postmortem (the actual AI-cost-incurring action) had zero
-- rate limiting -- a compromised or malicious account could hammer either
-- endpoint without limit. DB-backed for the same reason as login rate
-- limiting: this backend runs as Vercel serverless functions with no
-- shared process memory across instances/cold starts.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.api_action_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    action text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS api_action_events_user_action_created_idx
    ON public.api_action_events (user_id, action, created_at);
