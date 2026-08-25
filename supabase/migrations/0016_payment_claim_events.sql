-- Real payment-engineering practice, not just this app's own convention:
-- never overwrite financial history. payment_claims.status/reviewed_by
-- get overwritten in place (correct for "what is the current state" but
-- loses "what actually happened, in order, by whom" the moment a second
-- transition occurs). This is the append-only ledger alongside it -- one
-- row per state transition, never updated or deleted, so a claim's full
-- history (created -> bank_verified -> approved, or any other order) is
-- always reconstructable for reconciliation or a dispute, even long after
-- the claim itself only shows its current state.
CREATE TABLE IF NOT EXISTS public.payment_claim_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id uuid NOT NULL REFERENCES public.payment_claims(id) ON DELETE CASCADE,
    event_type text NOT NULL CHECK (event_type IN ('created', 'bank_verified', 'approved', 'rejected')),
    actor text NOT NULL,
    detail text,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS payment_claim_events_claim_id_idx ON public.payment_claim_events (claim_id, created_at);
