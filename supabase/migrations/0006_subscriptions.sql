-- Real payment gate: the product's actual work (creating incidents,
-- recording evidence, drafting, publishing) requires an active Stripe
-- subscription, tracked directly on the account. Idempotent, matching the
-- existing migrations' style.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_customer_id text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_subscription_id text;
-- 'none' until a checkout completes; Stripe's own subscription.status
-- values thereafter (active, trialing, past_due, canceled, unpaid, ...) --
-- stored verbatim rather than collapsed to a boolean, so a webhook handler
-- never has to guess what a status it hasn't seen before should map to.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS subscription_status text NOT NULL DEFAULT 'none';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS current_period_end bigint;

CREATE UNIQUE INDEX IF NOT EXISTS users_stripe_customer_id_idx ON public.users (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS users_stripe_subscription_id_idx ON public.users (stripe_subscription_id)
    WHERE stripe_subscription_id IS NOT NULL;
