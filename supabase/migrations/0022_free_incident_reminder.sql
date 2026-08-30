-- Tracks whether a one-time "you used your free postmortem, here's how to
-- keep it" nudge email has already been sent to an account -- so a
-- scheduled job can find "used the free incident, never subscribed, not
-- reminded yet" accounts without ever emailing the same person twice.
-- NULL means never sent; set once, on send, never cleared or reset.
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_incident_reminder_sent_at bigint;
