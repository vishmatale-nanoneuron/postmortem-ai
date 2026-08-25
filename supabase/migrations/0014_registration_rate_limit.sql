-- Backs per-IP registration rate limiting. A dedicated table, not
-- login_attempts, because that table's succeeded/email columns carry a
-- specific meaning for the login limiter (is_login_rate_limited counts
-- succeeded=false rows) -- reusing it for registration would risk
-- cross-contaminating that count. No FK to users, deliberately: an IP can
-- attempt registration before any account exists.
CREATE TABLE IF NOT EXISTS public.registration_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ip text NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS registration_attempts_ip_created_idx ON public.registration_attempts (ip, created_at);
