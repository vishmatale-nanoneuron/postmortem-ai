-- Real user accounts, replacing the hardcoded DEMO_CLIENT_EMAIL identity
-- every route used until now. Idempotent, matching the existing two
-- migrations' style.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at bigint NOT NULL
);
