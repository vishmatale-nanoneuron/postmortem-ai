-- Adds 'annotated' to payment_claim_events.event_type's allowlist -- a
-- founder-authored correction/note appended to a claim's audit trail
-- without touching payment_claims.status (see founder.py's
-- annotate_payment_claim). Postgres has no ALTER CHECK; drop and recreate
-- the constraint by name, which is idempotent (DROP ... IF EXISTS) and
-- safe to replay.
ALTER TABLE public.payment_claim_events DROP CONSTRAINT IF EXISTS payment_claim_events_event_type_check;

ALTER TABLE public.payment_claim_events
    ADD CONSTRAINT payment_claim_events_event_type_check
    CHECK (event_type IN ('created', 'bank_verified', 'approved', 'rejected', 'annotated'));
