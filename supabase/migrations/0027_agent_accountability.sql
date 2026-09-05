-- Agent accountability: account_activity_log (0024) already recorded "who
-- did what, when" for REST-driven actions, but had no way to tell a client
-- clicking a button in their browser apart from an AI agent calling the
-- same action via MCP (Claude Desktop, etc.) -- both looked identical.
-- Adding `source` lets the same, already-real audit trail also answer
-- "was this me or an agent," the actual accountability question, without
-- a second table to keep in sync with the first.
--
-- DEFAULT 'web' backfills every existing row correctly: every action
-- logged before this migration genuinely was REST/browser-driven -- MCP
-- tool calls never wrote to this table at all until this same change
-- wires them in (see mcp_server.py's _audited()).
ALTER TABLE public.account_activity_log ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'web';

CREATE INDEX IF NOT EXISTS account_activity_log_source_idx
    ON public.account_activity_log (source, created_at DESC);
