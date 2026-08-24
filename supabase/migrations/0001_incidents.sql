-- Minimal incidents table for the MVP slice. No auth yet -- client_email is
-- always the fixed demo identity used throughout apps/api/app/api/v1
-- (DEMO_CLIENT_EMAIL). Real multi-tenant scoping is a later phase; the shape
-- here (a client_email column, scoped lookups) is deliberately left in place
-- so that phase is a matter of wiring real identity in, not restructuring
-- the schema.
CREATE TABLE IF NOT EXISTS public.incidents (
    id text PRIMARY KEY,
    client_email text NOT NULL,
    title text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('sev1', 'sev2', 'sev3', 'sev4')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    impact text,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS incidents_client_email_idx ON public.incidents (client_email);
