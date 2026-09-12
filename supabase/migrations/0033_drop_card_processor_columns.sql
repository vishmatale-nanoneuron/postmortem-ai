-- The card processor was removed on 2026-09-13 on the owner's instruction:
-- UPI and international wire are the only payment rails. Nothing reads
-- these two columns any more (billing.py's checkout/portal/webhook routes
-- are gone), so they go too, along with their partial unique indexes.
-- subscription_status and current_period_end stay: they are what a
-- founder-approved manual claim sets, and what the paywall reads.
--
-- DROP ... IF EXISTS makes this replay-safe, the same as every other
-- migration here.
DROP INDEX IF EXISTS public.users_stripe_customer_id_idx;
DROP INDEX IF EXISTS public.users_stripe_subscription_id_idx;
ALTER TABLE public.users DROP COLUMN IF EXISTS stripe_customer_id;
ALTER TABLE public.users DROP COLUMN IF EXISTS stripe_subscription_id;
