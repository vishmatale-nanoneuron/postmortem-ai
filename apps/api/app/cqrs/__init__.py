"""Command/query separation, scoped to the one domain that actually needs
it: the account activity audit trail (see activity.py). Not a general
framework -- this app is a single Postgres instance with a single writer,
so there is no separate read model/projection to build and no message bus
worth adding; "CQRS" here means what it names at this scale: a Command
type + handler for every write, a Query type + handler for every read,
each with exactly one implementation reused by every caller (REST routes
in api/v1/, MCP tools in mcp_server.py) instead of duplicated SQL."""
