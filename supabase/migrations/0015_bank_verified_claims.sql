-- Backs bank-alert auto-verification (app/bank_alerts.py). Deliberately
-- does NOT grant access on its own -- a matching real bank alert marks a
-- claim bank_verified, but only a founder clicking approve in the
-- dashboard ever flips status to 'approved' and activates access. This
-- separates "verified" (what a machine can confirm) from "authorized"
-- (a deliberate human act), per explicit instruction: no client gets
-- access without a founder approving it, automation or not.
ALTER TABLE public.payment_claims ADD COLUMN IF NOT EXISTS bank_verified boolean NOT NULL DEFAULT false;
ALTER TABLE public.payment_claims ADD COLUMN IF NOT EXISTS bank_verified_at bigint;
