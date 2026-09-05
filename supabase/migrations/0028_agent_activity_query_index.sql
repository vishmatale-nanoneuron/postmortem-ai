-- Supports the new platform-wide activity-log query (api/v1/founder.py's
-- GET /activity-log, cqrs/activity.py's handle_activity_log_query) when no
-- client_email or source filter narrows it: keyset pagination orders by
-- (created_at DESC, id DESC), and the existing indexes from 0024/0027
-- (client_email, created_at) / (source, created_at) don't cover an
-- unfiltered scan of every account's rows.
CREATE INDEX IF NOT EXISTS account_activity_log_created_at_id_idx
    ON public.account_activity_log (created_at DESC, id DESC);
