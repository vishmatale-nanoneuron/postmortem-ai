-- Adds international SWIFT wire as a second manual payment method
-- alongside UPI, reusing the same claim/review table rather than a
-- parallel one. `amount_inr` predates this and is kept as the generic
-- amount column (its name is now a historical artifact, not a currency
-- guarantee) rather than renamed, since migrations here are additive-only;
-- `currency` says what it actually means.
ALTER TABLE public.payment_claims ADD COLUMN IF NOT EXISTS method text NOT NULL DEFAULT 'upi'
    CHECK (method IN ('upi', 'wire'));
ALTER TABLE public.payment_claims ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'INR'
    CHECK (currency IN ('INR', 'USD', 'GBP', 'EUR'));
