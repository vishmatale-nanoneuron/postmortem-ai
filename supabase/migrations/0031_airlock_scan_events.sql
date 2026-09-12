-- Airlock's audit log: one immutable row per scan decision.
--
-- This is the thing the product is actually for. A guard that blocks an
-- injection and keeps no record of it has stopped one attack; a guard that
-- records every decision lets a team answer "what did this agent see, and
-- what did we do about it" months later, which is the question an auditor
-- asks and the reason this table exists at all.
--
-- What is deliberately NOT here:
--
-- 1. The scanned content. Only a SHA-256 of it, its byte count, and (for a
--    non-allow verdict, and never from the public playground) a redacted
--    excerpt. The public page promises exactly this, so the schema has no
--    column that could hold the raw text even by accident.
-- 2. Any account or client identifier. Attribution would be useful for
--    metering later, but it collides head-on with an invariant this
--    product already makes: account deletion is a real erasure, in one
--    transaction. An append-only table cannot participate in an erasure --
--    the DELETE would raise. Rather than weaken either guarantee, rows here
--    carry no personal data, so there is nothing about a person to erase.
--    Metering, when it is built, needs a separate per-tenant counter table
--    that CAN be deleted, not a relaxation of this one.
-- 3. The client IP. Rate limiting uses its own attempts table (below),
--    the same shape as 0014/0020/0030, and that one is prunable.
CREATE TABLE IF NOT EXISTS public.airlock_scan_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- 'ingress' (content heading into an agent) or 'egress' (a call heading
    -- out of one). CHECKed rather than trusted: every write path must
    -- produce a value the reader already understands.
    kind text NOT NULL,
    source text,
    verdict text NOT NULL,
    score double precision NOT NULL,
    -- Rule ids that fired, e.g. ["IO-001","EX-003"]. jsonb so a later
    -- "which rule fires most" query is an index away rather than a rewrite.
    matched_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_sha256 text NOT NULL,
    content_bytes integer NOT NULL,
    excerpt text,
    latency_ms integer NOT NULL DEFAULT 0,
    created_at bigint NOT NULL
);

DO $$
BEGIN
    ALTER TABLE public.airlock_scan_events
        ADD CONSTRAINT airlock_scan_events_kind_check CHECK (kind IN ('ingress', 'egress'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE public.airlock_scan_events
        ADD CONSTRAINT airlock_scan_events_verdict_check CHECK (verdict IN ('allow', 'flag', 'block'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS airlock_scan_events_created_idx
    ON public.airlock_scan_events (created_at DESC);
CREATE INDEX IF NOT EXISTS airlock_scan_events_verdict_created_idx
    ON public.airlock_scan_events (verdict, created_at DESC);

-- Append-only, enforced HERE rather than in application code.
--
-- This is the whole difference between an audit log and a table that
-- happens to be written once. Application code can be bypassed by the next
-- endpoint someone adds, by a migration script, by anything else holding
-- the same connection string. A BEFORE UPDATE OR DELETE trigger cannot: the
-- database refuses, whoever is asking. It is also the specific property the
-- public /airlock page claims, so it must be true of the database and not
-- of a convention.
CREATE OR REPLACE FUNCTION public.airlock_scan_events_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'airlock_scan_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS airlock_scan_events_immutable ON public.airlock_scan_events;
CREATE TRIGGER airlock_scan_events_immutable
    BEFORE UPDATE OR DELETE ON public.airlock_scan_events
    FOR EACH ROW EXECUTE FUNCTION public.airlock_scan_events_block_mutation();

-- ...and TRUNCATE, which the trigger above does NOT cover.
--
-- Verified directly rather than assumed: with only the row-level trigger in
-- place, `TRUNCATE airlock_scan_events` emptied the table and reported
-- success. A BEFORE DELETE trigger is FOR EACH ROW, and TRUNCATE deletes no
-- rows -- it drops the file. So the "append-only" guarantee had a hole wide
-- enough to erase the entire audit log in one statement, silently. A
-- statement-level BEFORE TRUNCATE trigger is what actually closes it.
CREATE OR REPLACE FUNCTION public.airlock_scan_events_block_truncate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'airlock_scan_events is append-only and cannot be truncated';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS airlock_scan_events_no_truncate ON public.airlock_scan_events;
CREATE TRIGGER airlock_scan_events_no_truncate
    BEFORE TRUNCATE ON public.airlock_scan_events
    FOR EACH STATEMENT EXECUTE FUNCTION public.airlock_scan_events_block_truncate();

-- Per-IP bound on the free public scanner, so one source cannot turn an
-- unauthenticated endpoint into an append-only table that grows forever.
-- Prunable by design, unlike the log above.
CREATE TABLE IF NOT EXISTS public.airlock_scan_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ip text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS airlock_scan_attempts_ip_created_idx
    ON public.airlock_scan_attempts (ip, created_at);
