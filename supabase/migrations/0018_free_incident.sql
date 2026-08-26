-- One free postmortem per account before the paywall kicks in -- lets a
-- prospect try the real core loop (evidence -> grounded draft) without
-- paying first, which the previous all-or-nothing gate never allowed.
-- free_incident_id records which single incident an unpaid account is
-- allowed to keep working on; a second incident, and publishing on any
-- incident, still require a real subscription (enforced in app code, not
-- here -- this column only tracks which slot has been used).
ALTER TABLE users ADD COLUMN IF NOT EXISTS free_incident_id text REFERENCES incidents(id) ON DELETE SET NULL;
