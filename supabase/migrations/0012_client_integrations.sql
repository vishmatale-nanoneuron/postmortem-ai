-- Per-client integrations (not founder-level config like Stripe/UPI/wire
-- above) -- each account connects its OWN Slack workspace and Linear
-- workspace. Slack via a plain Incoming Webhook URL (no OAuth app/review
-- needed -- the same "founder provides a webhook URL" pattern as
-- alerting.py, just per-user instead of global). Linear via a personal
-- API key (simplest real integration; a full public OAuth app is a much
-- bigger lift -- registering an OAuth app in Linear's developer console,
-- hosting a redirect URI -- deferred, not built).
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS slack_webhook_url text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS linear_api_key text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS linear_team_id text;
