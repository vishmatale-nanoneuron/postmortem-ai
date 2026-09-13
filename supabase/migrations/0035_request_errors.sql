-- Application errors, recorded by the API's own unhandled-exception
-- handler. Before this table, a 500 in production was a line in a log
-- stream nobody reads; the founder learned of a break when a customer
-- said so. Each row is one failed request: what route, what exception
-- type, the request id the customer was shown, and a fingerprint (type +
-- method + path) so the same fault a hundred times is one problem, not a
-- hundred. The message is the exception's text, truncated -- never a
-- request body, never a stack trace.
--
-- Written best-effort: the handler that writes here must never itself
-- fail the response, and a database outage is exactly the case where the
-- write cannot happen -- the log stream still has that one.
--
-- Read by the founder dashboard only. No user, no key, no IP; erasure is
-- unaffected. Pruned by the founder route's 90-day window on read; rows
-- older than that are deleted opportunistically.

CREATE TABLE IF NOT EXISTS public.request_errors (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at bigint NOT NULL,
    method text NOT NULL,
    path text NOT NULL,
    status integer NOT NULL DEFAULT 500,
    request_id text NOT NULL,
    error_type text NOT NULL,
    message text NOT NULL DEFAULT '',
    fingerprint text NOT NULL,
    -- True on the one row per fingerprint per day that triggered the
    -- founder email, so the dashboard can show when they were told.
    notified boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS request_errors_created_at_idx ON public.request_errors (created_at DESC);
CREATE INDEX IF NOT EXISTS request_errors_fingerprint_created_idx ON public.request_errors (fingerprint, created_at DESC);
