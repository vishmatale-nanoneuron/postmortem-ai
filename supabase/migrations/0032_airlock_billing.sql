-- Airlock becomes a paid, metered service: API keys, prepaid scan credits,
-- and a ledger. This is the "separate per-tenant counter table that CAN be
-- deleted" that 0031's header said metering would need -- built here rather
-- than by weakening airlock_scan_events, which stays append-only and
-- unattributed.
--
-- The billing shape is prepaid packs, not a subscription and not post-paid
-- metering. That is dictated by the rails that exist: UPI and international
-- wire, each approved by hand from the founder dashboard. A one-off payment
-- that buys N scans fits those rails exactly (it is the same payment_claims
-- row, with two extra columns saying what it buys); a metered monthly
-- invoice would need live card billing this product does not have.
--
-- Three tables plus two columns:
--
-- airlock_api_keys        one row per issued key. The key itself is never
--                         stored -- only a SHA-256 of it and an 8-character
--                         display prefix. Keys are 256-bit random secrets, so
--                         a fast hash is the right primitive (scrypt is for
--                         low-entropy passwords, and would add ~100 ms of CPU
--                         to every scan).
-- airlock_credit_balances one row per account, the current balance. The
--                         CHECK (balance >= 0) plus a conditional UPDATE is
--                         what makes the debit atomic under concurrency: two
--                         scans racing for the last credit both UPDATE the
--                         same row, Postgres serialises them on the row lock,
--                         and the second one's `WHERE balance >= 1` sees 0.
--                         No advisory lock needed.
-- airlock_credit_ledger   every movement, signed. Purchases and grants are
--                         positive, each scan is -1. The balance is
--                         reconstructible as SUM(delta); the balances table is
--                         the fast path, the ledger is the statement.
--
-- All three cascade from users: an account erasure (auth.delete_account)
-- takes its keys, balance and ledger with it in the same transaction, which
-- keeps the privacy policy's "deletion is an erasure" claim true.

CREATE TABLE IF NOT EXISTS public.airlock_api_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    label text NOT NULL DEFAULT '',
    -- First characters of the key, e.g. 'alk_3f9a2b1c'. Shown in the
    -- dashboard so a customer can tell two keys apart; useless to an
    -- attacker on its own.
    prefix text NOT NULL,
    key_hash text NOT NULL,
    created_at bigint NOT NULL,
    last_used_at bigint,
    -- Revocation is a timestamp, not a delete: the ledger references keys
    -- (below) and a customer's statement should still say which key spent
    -- what after that key is gone.
    revoked_at bigint
);

CREATE UNIQUE INDEX IF NOT EXISTS airlock_api_keys_key_hash_idx ON public.airlock_api_keys (key_hash);
CREATE INDEX IF NOT EXISTS airlock_api_keys_user_id_idx ON public.airlock_api_keys (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.airlock_credit_balances (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    balance bigint NOT NULL DEFAULT 0 CHECK (balance >= 0),
    updated_at bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS public.airlock_credit_ledger (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    -- Which key spent it. NULL for purchases/grants, and for scans made from
    -- the signed-in playground (which has no key). SET NULL rather than
    -- CASCADE so deleting a key row -- which nothing does today -- could not
    -- silently delete a customer's usage history.
    api_key_id uuid REFERENCES public.airlock_api_keys(id) ON DELETE SET NULL,
    delta integer NOT NULL CHECK (delta <> 0),
    reason text NOT NULL,
    -- A payment_claims id for a purchase, a founder note for a grant, NULL
    -- for a scan. Free text on purpose: it is a human-readable statement
    -- line, not a foreign key.
    reference text,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS airlock_credit_ledger_user_idx ON public.airlock_credit_ledger (user_id, created_at DESC);

DO $$
BEGIN
    ALTER TABLE public.airlock_credit_ledger
        ADD CONSTRAINT airlock_credit_ledger_reason_check
        CHECK (reason IN ('purchase', 'grant', 'scan', 'deep_scan', 'egress', 'refund', 'adjustment'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- A payment claim now says which product it is for and, for Airlock, how
-- many scans it buys. Stored on the claim rather than recomputed at
-- approval time for the same reason 0029 stores billing_period: what the
-- founder grants must be exactly what the customer paid for, at the price
-- that was current when they paid, even if the pack size changes later.
-- DEFAULT 'postmortem' backfills every existing row correctly -- every claim
-- before this migration was a PostMortem AI subscription.
ALTER TABLE public.payment_claims
    ADD COLUMN IF NOT EXISTS product text NOT NULL DEFAULT 'postmortem';

ALTER TABLE public.payment_claims
    ADD COLUMN IF NOT EXISTS scan_credits integer;

DO $$
BEGIN
    ALTER TABLE public.payment_claims
        ADD CONSTRAINT payment_claims_product_check
        CHECK (product IN ('postmortem', 'airlock'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- An Airlock claim must say what it buys; a PostMortem claim must not
-- pretend to. Enforced here so approve_payment_claim can trust the column
-- rather than re-deriving it.
DO $$
BEGIN
    ALTER TABLE public.payment_claims
        ADD CONSTRAINT payment_claims_scan_credits_check
        CHECK (
            (product = 'airlock' AND scan_credits IS NOT NULL AND scan_credits > 0)
            OR (product <> 'airlock' AND scan_credits IS NULL)
        );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
