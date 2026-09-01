-- A real "who did what, when" audit trail for an account's own actions --
-- the same append-only-ledger discipline this app already applies to
-- payment claims (payment_claim_events) and postmortem drafts
-- (postmortem_draft_history), extended to the account-level actions that
-- actually matter for a real audit: creating an incident, publishing a
-- postmortem, changing status, exporting data. Not tied to a single
-- incident_id via a foreign key (unlike the two tables above) since some
-- actions (export) aren't incident-scoped at all -- incident_id stays a
-- plain nullable column, not a FK, so a row survives even if the incident
-- it references is never deleted (incidents never cascade-delete anyway)
-- or, in a future case, if one somehow did.
CREATE TABLE IF NOT EXISTS public.account_activity_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_email text NOT NULL,
    action text NOT NULL,
    incident_id text,
    detail text,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS account_activity_log_client_email_idx
    ON public.account_activity_log (client_email, created_at DESC);
