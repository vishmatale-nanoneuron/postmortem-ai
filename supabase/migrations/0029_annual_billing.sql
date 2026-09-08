-- Annual billing for the manual (UPI/wire) rails.
--
-- The driver is international wire economics, not a pricing experiment: a
-- SWIFT wire sent with the OUR charge code (which the payment-details email
-- now requires, so the full amount actually lands and bank_alerts.py can
-- match it) costs the sender roughly USD 15-40 in fees. Against a USD 15
-- monthly subscription that is a >100% surcharge every single month, which
-- no customer will pay twice. Against an annual payment it is a one-off
-- cost on a much larger transfer.
--
-- Stored on the claim rather than inferred from the amount: the amount alone
-- is ambiguous (a currency's annual price could coincide with another's
-- monthly), and approve_payment_claim needs to know unambiguously how long
-- an approval should grant. DEFAULT 'monthly' backfills every existing row
-- correctly -- every claim taken before this migration was a monthly one.
ALTER TABLE public.payment_claims
    ADD COLUMN IF NOT EXISTS billing_period text NOT NULL DEFAULT 'monthly';

-- Refuses a typo'd period at the database level rather than trusting every
-- future write path to validate it, the same discipline incident_postmortems
-- uses for its published/approver constraint.
DO $$
BEGIN
    ALTER TABLE public.payment_claims
        ADD CONSTRAINT payment_claims_billing_period_check
        CHECK (billing_period IN ('monthly', 'annual'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
