-- Manual UPI payment: a client pays the founder's UPI ID directly and
-- submits the transaction reference here; the founder reviews and approves
-- from the founder dashboard, which sets users.subscription_status='active'
-- the same way a Stripe webhook would. No gateway involved -- real money,
-- human-verified. Idempotent, matching the existing migrations' style.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.payment_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    amount_inr integer NOT NULL CHECK (amount_inr > 0),
    reference text NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_by text,
    reviewed_at bigint,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS payment_claims_user_id_idx ON public.payment_claims (user_id);
CREATE INDEX IF NOT EXISTS payment_claims_status_idx ON public.payment_claims (status);
