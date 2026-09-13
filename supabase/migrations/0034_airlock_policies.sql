-- Airlock per-account policy: the two verdict thresholds, the rules an
-- account has muted, and a standing egress allowlist. Until now all of
-- these were per-call parameters (the allowlist) or fixed constants (the
-- thresholds), and there was no way to mute a rule that fires on a
-- customer's own legitimate documents short of ignoring the verdict.
--
-- One row per account, absent until the account changes something -- the
-- scanner treats a missing row as the defaults (block >= 0.75, flag >=
-- 0.40, nothing muted, no allowlist), so no backfill is needed and a
-- customer who never opens the policy page gets exactly the behaviour
-- they had before.
--
-- Read on every keyed scan, so it is joined into the key lookup that
-- already runs (cqrs/airlock_billing.resolve_api_key) rather than fetched
-- separately: the scan path is one round trip for auth and one for the
-- debit, and a policy must not add a third.
--
-- Cascades from users, like the keys, balance and ledger in 0032: an
-- account erasure takes its policy with it.
--
-- The CHECKs hold the invariants the API also validates, so a row can
-- never say "flag above block" or a threshold outside (0, 1] no matter
-- which path wrote it.

CREATE TABLE IF NOT EXISTS public.airlock_policies (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    block_threshold double precision NOT NULL DEFAULT 0.75
        CHECK (block_threshold > 0 AND block_threshold <= 1),
    flag_threshold double precision NOT NULL DEFAULT 0.40
        CHECK (flag_threshold > 0 AND flag_threshold <= block_threshold),
    -- Rule ids from airlock/rules.py (e.g. 'IO-001'). Validated against
    -- the live rule list by the API; kept as text so a rule retired from
    -- the engine does not break the row that muted it.
    muted_rules text[] NOT NULL DEFAULT '{}',
    -- Hostnames (or host suffixes) an egress call may target without
    -- naming them per call. Merged with any allowlist sent on the call.
    egress_allowlist text[] NOT NULL DEFAULT '{}',
    updated_at bigint NOT NULL
);
