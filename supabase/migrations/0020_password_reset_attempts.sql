-- Backs per-IP password-reset-request rate limiting -- same reasoning and
-- shape as 0014_registration_rate_limit.sql's registration_attempts: a
-- dedicated table, not login_attempts, since that table's succeeded/email
-- columns carry a specific meaning for the login limiter. No FK to users
-- deliberately: the endpoint is intentionally reachable by email address
-- that may or may not correspond to a real account (never revealing which,
-- to avoid account enumeration).
CREATE TABLE IF NOT EXISTS public.password_reset_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ip text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS password_reset_attempts_ip_created_idx ON public.password_reset_attempts (ip, created_at);
