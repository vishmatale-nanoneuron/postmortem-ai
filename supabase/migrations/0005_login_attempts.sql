-- Backs real login rate limiting. Must be a real table, not an in-memory
-- counter: this backend runs as Vercel serverless functions, which do not
-- share process memory across instances/cold starts, so an in-process
-- rate limiter would silently do nothing in production.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.login_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    ip text NOT NULL,
    succeeded boolean NOT NULL,
    created_at bigint NOT NULL
);

CREATE INDEX IF NOT EXISTS login_attempts_email_created_idx ON public.login_attempts (email, created_at);
CREATE INDEX IF NOT EXISTS login_attempts_ip_created_idx ON public.login_attempts (ip, created_at);
