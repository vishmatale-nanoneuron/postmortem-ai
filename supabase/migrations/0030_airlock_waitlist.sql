-- Airlock's early-access list.
--
-- Airlock (a prompt-injection and exfiltration guard that sits between an
-- agent and untrusted content) is a second product. Its code is not hosted
-- yet: there is no scan endpoint a customer can call, no metering and no
-- checkout. So the public /airlock page cannot sell anything, and the one
-- honest conversion it can offer is "tell me when it is hosted" -- which is
-- also the measurement the pivot actually needs (how many teams want this
-- before a line of billing code is written).
--
-- Deliberately NOT a column on users: joining the waitlist must not require
-- an account, and a waitlist row is not an account. The two tables share no
-- foreign key for the same reason password_reset_attempts has none -- the
-- address may or may not correspond to a real user, and the endpoint must
-- never reveal which.
CREATE TABLE IF NOT EXISTS public.airlock_waitlist (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    company text,
    -- What they want to guard. Free text: the whole point of the list at
    -- this stage is to learn which agent shapes people are worried about,
    -- and a dropdown would only return the options I guessed.
    use_case text,
    created_at bigint NOT NULL
);

-- One row per address, case-insensitively. Makes re-submitting idempotent,
-- which is what lets the endpoint answer 202 to a duplicate exactly as it
-- does to a new signup -- so the response can never be used to test whether
-- an address is already on the list.
CREATE UNIQUE INDEX IF NOT EXISTS airlock_waitlist_email_key
    ON public.airlock_waitlist (lower(email));

-- Backs the per-IP limit on the endpoint. A separate table from the list
-- itself, and not just a count over airlock_waitlist, because the insert is
-- ON CONFLICT DO NOTHING: re-posting one address adds no row, so counting
-- rows would leave that path unbounded. Same shape and reasoning as
-- 0014_registration_rate_limit.sql and 0020_password_reset_attempts.sql.
CREATE TABLE IF NOT EXISTS public.airlock_waitlist_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ip text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS airlock_waitlist_attempts_ip_created_idx
    ON public.airlock_waitlist_attempts (ip, created_at);
