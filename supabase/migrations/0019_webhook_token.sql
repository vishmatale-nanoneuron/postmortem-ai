-- Real webhook ingestion: lets an external tool (monitoring, alerting, a
-- script -- anything that can POST JSON) create an incident or append
-- evidence without a signed-in browser session, authenticated by a
-- per-account secret token in the URL rather than a session cookie
-- (there is no session to have -- the caller isn't a browser). Every
-- account gets one on creation; rotatable from account settings if it
-- leaks (see POST /v1/webhooks/token/rotate).
ALTER TABLE users ADD COLUMN IF NOT EXISTS webhook_token text UNIQUE;

-- Backfill existing accounts (registered before this migration) with a
-- real token -- encode(gen_random_bytes(24), 'hex') gives a 48-hex-char
-- token, same entropy class as this app's session tokens elsewhere.
UPDATE users SET webhook_token = encode(gen_random_bytes(24), 'hex') WHERE webhook_token IS NULL;
