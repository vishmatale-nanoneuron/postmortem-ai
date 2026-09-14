-- Airlock tuning feedback: a customer tells the guard it was wrong about
-- a specific decision -- a false positive on their own documents, or an
-- injection it missed -- and that record is what tunes their account.
--
-- One row per report. The content of what was scanned is NOT stored
-- unless the customer chose to include it: the audit log never holds
-- content (0031), the privacy policy promises scans are not kept, and
-- that promise is kept here too. A row with content is the customer's
-- explicit, per-report consent to keep that one text for tuning their own
-- account and, when exported, as their own fine-tuning example. Nothing
-- here trains anything for anyone else: the founder sees counts per rule
-- across accounts, never content.
--
-- What it feeds:
--   suggestions   -- rules that keep producing reported false positives on
--                    an account become "mute this rule" suggestions; misses
--                    become "turn on deep scan for this source" suggestions;
--   export        -- the account's consented examples in the same tuning
--                    format as benchmarks/finetune (scripts/airlock_finetune_
--                    dataset.py), for a customer tuning their own classifier;
--   the engine    -- aggregate false-positive counts per rule, across
--                    accounts, are the signal for changing a rule's weight
--                    or pattern in rules.py, benchmarked before it ships.
--
-- Cascades from users: erasure takes every report, content included.

CREATE TABLE IF NOT EXISTS public.airlock_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    -- The decision being disputed, by the hash the scan response carried.
    content_sha256 text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('ingress', 'egress')),
    verdict_given text NOT NULL CHECK (verdict_given IN ('allow', 'flag', 'block')),
    verdict_expected text NOT NULL CHECK (verdict_expected IN ('allow', 'flag', 'block')),
    -- Rule ids that fired on the disputed decision, as the response listed them.
    rule_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source text,
    note text,
    -- Present only when the customer ticked "include the text". Bounded by
    -- the API; erased with the account.
    content text,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS airlock_feedback_user_created_idx ON public.airlock_feedback (user_id, created_at DESC);
