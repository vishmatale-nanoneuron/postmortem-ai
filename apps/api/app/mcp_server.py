"""The MCP server: exposes this product's real backend + database as MCP
tools, over the same auth (JWT session tokens) and the same business logic
already proven by the REST API -- tools call the actual route functions in
api/v1/postmortems.py and api/v1/founder.py directly rather than
duplicating their SQL, so there is exactly one implementation of each
piece of business logic, not two that can drift apart.

Auth: FastMCP 1.9.x's Context has no direct HTTP-request accessor, so
authentication happens one layer down, in MCPBearerAuthMiddleware, which
resolves an `Authorization: Bearer <session JWT>` header (the same tokens
/v1/auth/login issues) into a User stored in a contextvar every tool reads
from. Subscription gating mirrors the REST API's own three-tier scheme
exactly (require_mcp_active_subscription /
require_mcp_active_subscription_or_free_slot /
_or_free_incident, matching auth.py's own three functions) -- an MCP
client gets no more and no less access than a browser session would,
including the free-tier allowance (fixed here after being found missing,
the same bug class the webhook path had).
"""

import contextvars
import functools
import logging
import re
import time
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .ai.embeddings import embed_text
from .ai.model_router import create_model_provider
from .ai.rag import find_similar_postmortems, get_embedding_client
from .api.v1 import founder as founder_routes
from .api.v1 import integrations as integrations_routes
from .api.v1 import postmortems as postmortem_routes
from .auth import User, _is_founder
from .cqrs.activity import ActivityLogFilter, handle_activity_log_query
from .database import Database
from .security.tokens import verify_token
from .settings import Settings

logger = logging.getLogger("postmortem_ai")

_current_user: contextvars.ContextVar[User | None] = contextvars.ContextVar("mcp_current_user", default=None)

# Column names redacted from run_read_only_sql results regardless of which
# table they come from -- credential-shaped columns are never readable
# through this tool, full stop, not just "not selected by default."
_REDACTED_COLUMNS = {"password_hash", "stripe_customer_id", "stripe_subscription_id"}

# Tools whose shared REST route body already writes its own
# account_activity_log row on success (with a real source= passed
# through) -- _audited() skips its own *success* logging for these two
# specifically, to avoid double-counting. Denials/errors still go through
# the normal path regardless, since those never reach the inner route
# body (and its own log_activity call) at all -- see _audited's docstring.
_SELF_LOGGED_TOOLS = {"create_incident", "publish_postmortem"}


def current_mcp_user() -> User:
    user = _current_user.get()
    if user is None:
        raise PermissionError("Not authenticated")
    return user


def require_mcp_founder() -> User:
    user = current_mcp_user()
    if not user.is_founder:
        raise PermissionError("Founder access required")
    return user


def require_mcp_active_subscription() -> User:
    user = current_mcp_user()
    if not user.has_active_subscription:
        raise PermissionError("An active subscription is required")
    return user


def require_mcp_active_subscription_or_free_slot() -> User:
    """Mirrors auth.require_active_subscription_or_free_slot exactly --
    gates incident *creation* specifically, letting a brand-new unpaid
    account through once (its own free incident). Found via a real audit
    (not assumed) that create_incident/add_evidence/draft_postmortem here
    all used the flat require_mcp_active_subscription() above -- the same
    bug class as the webhook path's own free-tier gap fixed earlier: a
    brand-new signup calling this tool via an MCP client (Claude Desktop,
    etc.) got an immediate 'subscription required' error on their very
    first call, unable to reach the free incident the REST API and the
    webhook path both correctly grant."""
    user = current_mcp_user()
    if user.has_active_subscription or user.has_free_incident_available:
        return user
    raise PermissionError("An active subscription is required")


def require_mcp_active_subscription_or_free_incident(incident_id: str) -> User:
    """Mirrors auth.require_active_subscription_or_free_incident -- gates
    actions on an *existing* incident (evidence, drafting): a subscriber,
    or a free-tier account acting on specifically the one incident its
    free slot was spent on, never any other incident_id."""
    user = current_mcp_user()
    if user.has_active_subscription:
        return user
    if user.free_incident_id is not None and user.free_incident_id == incident_id:
        return user
    raise PermissionError("An active subscription is required")


class MCPBearerAuthMiddleware:
    """Resolves the caller from an Authorization: Bearer <session JWT>
    header into a User, stored in a contextvar tools read from."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        auth_header = request.headers.get("authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else None

        user: User | None = None
        if token:
            payload = verify_token(self.settings.session_secret, token)
            if payload is not None:
                database: Database = request.app.state.database
                # free_incident_id was missing from this SELECT entirely --
                # found via a real audit of the free-tier gating functions
                # above, not assumed. Every MCP-authenticated User's
                # free_incident_id defaulted to the dataclass's own None,
                # regardless of the real column value, which would have
                # made has_free_incident_available/the free-incident checks
                # above evaluate against a permanently-empty value instead
                # of the account's real state -- the same class of gap as
                # auth.py's own current_user (REST) and
                # user_by_webhook_token, both of which already select it.
                row = await database.fetch_one(
                    "SELECT id::text, email, subscription_status, current_period_end, free_incident_id"
                    " FROM users WHERE id=%s",
                    (payload.user_id,),
                )
                if row:
                    user = User(
                        id=row["id"],
                        email=row["email"],
                        is_founder=_is_founder(row["email"], self.settings.founder_email),
                        subscription_status=row["subscription_status"],
                        current_period_end=row["current_period_end"],
                        free_incident_id=row["free_incident_id"],
                    )

        if user is None:
            response = JSONResponse({"error": "Unauthorized -- pass Authorization: Bearer <session token>"}, status_code=401)
            await response(scope, receive, send)
            return

        reset_token = _current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_user.reset(reset_token)


def _redact_row(row: dict) -> dict:
    return {key: ("[redacted]" if key in _REDACTED_COLUMNS else value) for key, value in row.items()}


def build_mcp_server(get_database: Callable[[], Database], settings: Settings) -> FastMCP:
    # stateless_http=True was tried first (matching this codebase's usual
    # stance that nothing on this Vercel-serverless backend should depend
    # on in-memory continuity between requests -- see login rate limiting
    # and AI-run monitoring, both DB-backed for the same reason) but broke
    # the official MCP client's initialize handshake outright ("Session
    # terminated" on every connection, reproduced consistently, not a
    # fluke). Standard session mode instead -- a session lives for the
    # lifetime of one Vercel invocation's connection, which is the normal
    # way MCP streamable-http is used; a session that needs to outlive a
    # cold start is not a supported use case here, same tradeoff as
    # everything else in-memory in this deployment.
    # DNS-rebinding protection stays ON (the SDK's own secure default) --
    # explicitly allowlisting the real host(s) rather than disabling the
    # check entirely, since disabling it would remove a real defense for a
    # dependency-upgrade convenience. See settings.mcp_allowed_hosts's own
    # comment for why this exists at all.
    mcp = FastMCP(
        name="postmortem-ai",
        transport_security=TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts),
    )

    def _audited(tool_name: str) -> Callable[[Callable[..., Awaitable[object]]], Callable[..., Awaitable[object]]]:
        """Every tool call is logged before it runs -- actor, tool name --
        the same audit-before-execute discipline as nanoneuron-software-
        company's auditedTool(). Beyond that structured log line (real-time
        ops visibility, but ephemeral -- it ages out with Vercel's log
        retention and isn't queryable by the founder or the client), every
        call now also writes a durable row into account_activity_log with
        source='mcp_agent' -- the same real, already-existing audit trail
        REST actions write into (see postmortems.py's log_activity), now
        able to answer the actual accountability question: was this action
        taken by the client in their browser, or by an AI agent acting on
        their account via MCP.

        Nested inside build_mcp_server (not a module-level function, unlike
        before) specifically so it can close over get_database -- the audit
        row needs a real database write, which a module-level decorator
        defined before get_database exists has no way to reach.

        Records the *outcome*, not just the attempt: a PermissionError from
        one of the require_mcp_* gates above (called from inside the tool
        body, not by this wrapper) is caught here and logged as a denial --
        the actual "authorization layer" half of accountability, since
        without this an agent's blocked attempts were invisible, only its
        successes ever showed up anywhere. This denial path applies to
        every tool, including the two self-logged ones below -- a
        PermissionError there is raised before their shared REST route body
        (and its own internal log_activity call) is ever reached, so
        skipping this wrapper entirely for them would have silently lost
        exactly the denials that matter most.

        create_incident and publish_postmortem's *success* path is the one
        exception: their shared REST route bodies (see postmortems.py)
        already call log_activity themselves, with source="mcp_agent"
        passed through as a real keyword argument -- logging success again
        here would double-count those two specific actions, with the
        original row wrongly saying "web" regardless."""

        def decorator(fn: Callable[..., Awaitable[object]]) -> Callable[..., Awaitable[object]]:
            @functools.wraps(fn)
            async def wrapper(*args: object, **kwargs: object) -> object:
                user = _current_user.get()
                actor = user.email if user is not None else "unauthenticated"
                logger.info("mcp_tool_called", extra={"tool": tool_name, "actor": actor})

                incident_id = kwargs.get("incident_id") if isinstance(kwargs.get("incident_id"), str) else None
                started = time.monotonic()
                try:
                    result = await fn(*args, **kwargs)
                except PermissionError as exc:
                    if user is not None:
                        await postmortem_routes.log_activity(
                            get_database(), user.email, f"agent_{tool_name}_denied", incident_id, str(exc), source="mcp_agent"
                        )
                    raise
                except Exception as exc:
                    if user is not None:
                        await postmortem_routes.log_activity(
                            get_database(),
                            user.email,
                            f"agent_{tool_name}_failed",
                            incident_id,
                            str(exc)[:300],
                            source="mcp_agent",
                        )
                    raise
                else:
                    if user is not None and tool_name not in _SELF_LOGGED_TOOLS:
                        latency_ms = int((time.monotonic() - started) * 1000)
                        await postmortem_routes.log_activity(
                            get_database(), user.email, f"agent_{tool_name}", incident_id, f"{latency_ms}ms", source="mcp_agent"
                        )
                    return result

            return wrapper

        return decorator

    # ---- Founder-only tools ----------------------------------------

    @mcp.tool()
    @_audited("get_founder_summary")
    async def get_founder_summary() -> dict:
        """Platform-wide aggregates: users, incidents, postmortems, AI run
        success/failure/latency, pending payment claims, recent signups."""
        database = get_database()
        founder = require_mcp_founder()
        # founder_summary's `settings` param carries a real Depends() default
        # for FastAPI's own injector to resolve on an HTTP request -- this
        # call site invokes it directly instead, so that default is never
        # replaced; pass the real resolved Settings already in scope here.
        return await founder_routes.founder_summary(database=database, _founder=founder, settings=settings)

    @mcp.tool()
    @_audited("list_payment_claims")
    async def list_payment_claims() -> list[dict]:
        """Recent UPI/wire payment claims across every account, pending first."""
        database = get_database()
        founder = require_mcp_founder()
        claims = await founder_routes.list_payment_claims(database=database, _founder=founder)
        return [claim.model_dump() for claim in claims]

    @mcp.tool()
    @_audited("approve_payment_claim")
    async def approve_payment_claim(claim_id: str) -> dict:
        """Approve a payment claim -- grants the account an active
        subscription immediately, the same as a Stripe webhook would."""
        database = get_database()
        founder = require_mcp_founder()
        result = await founder_routes.approve_payment_claim(claim_id, database=database, founder=founder)
        return result.model_dump()

    @mcp.tool()
    @_audited("reject_payment_claim")
    async def reject_payment_claim(claim_id: str) -> dict:
        """Reject a payment claim -- the account stays blocked."""
        database = get_database()
        founder = require_mcp_founder()
        result = await founder_routes.reject_payment_claim(claim_id, database=database, founder=founder)
        return result.model_dump()

    @mcp.tool()
    @_audited("run_read_only_sql")
    async def run_read_only_sql(sql: str) -> list[dict]:
        """Run a single read-only SELECT/WITH query against the production
        database. Defense-in-depth, not just a regex check: exactly one
        statement, wrapped in a subquery with a hard LIMIT, executed inside
        a real Postgres read-only transaction (the database itself refuses
        a write, not just application-level discipline), and
        credential-shaped columns are redacted regardless of table."""
        database = get_database()
        require_mcp_founder()
        trimmed = sql.strip().rstrip(";")
        if ";" in trimmed:
            raise ValueError("Only a single statement is allowed")
        lowered = trimmed.lower().lstrip()
        if not lowered.startswith(("select", "with")):
            raise ValueError("Only a single SELECT or WITH statement is allowed")
        # A WITH clause can legally contain a data-modifying CTE (e.g.
        # `WITH d AS (DELETE FROM users RETURNING id) SELECT * FROM d`) --
        # single statement, starts with "with", passes both checks above.
        # Postgres's own read-only transaction refuses it regardless
        # (verified directly against a real database, not assumed), but
        # rejecting it here too gives a clean validation error instead of
        # a raw database error leaking through.
        if lowered.startswith("with") and re.search(r"\b(insert|update|delete|merge)\b", lowered):
            raise ValueError("Data-modifying CTEs are not allowed, even inside a WITH clause")

        wrapped = f"SELECT * FROM ({trimmed}) AS mcp_subquery LIMIT 500"
        async with database.read_only_transaction() as tx:
            rows = await tx.fetch_all(wrapped)
        return [_redact_row(dict(row)) for row in rows]

    @mcp.tool()
    @_audited("list_agent_activity")
    async def list_agent_activity(
        client_email: str | None = None,
        source: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        """The accountability audit trail across every account, not just
        the caller's own -- who (or which agent) did what, when. Pass
        source="mcp_agent" to see only actions other AI agents have taken,
        or client_email to scope to one account. This is the same query
        handler api/v1/founder.py's GET /activity-log REST route uses
        (cqrs.activity.handle_activity_log_query) -- reused rather than
        reimplemented, so a founder gets the identical answer whether they
        ask via this tool or the dashboard. Returns up to `limit` entries
        (max 200) plus a next_cursor to page further back if there are
        more."""
        database = get_database()
        require_mcp_founder()
        page = await handle_activity_log_query(
            database,
            ActivityLogFilter(client_email=client_email, source=source, limit=limit, cursor=cursor),
        )
        return {
            "entries": [
                {
                    "client_email": entry.client_email,
                    "action": entry.action,
                    "incident_id": entry.incident_id,
                    "detail": entry.detail,
                    "source": entry.source,
                    "created_at": entry.created_at,
                }
                for entry in page.entries
            ],
            "next_cursor": page.next_cursor,
        }

    # ---- Client-scoped tools (any authenticated user, own account only) --

    @mcp.tool()
    @_audited("list_incidents")
    async def list_incidents() -> list[dict]:
        """List the caller's own incidents."""
        database = get_database()
        user = current_mcp_user()
        return await postmortem_routes.list_incidents(database=database, user=user)

    @mcp.tool()
    @_audited("get_dashboard_summary")
    async def get_dashboard_summary() -> dict:
        """The caller's own dashboard aggregate: open/resolved incidents,
        drafted/published postmortems, recent incidents."""
        database = get_database()
        user = current_mcp_user()
        return await postmortem_routes.dashboard_summary(database=database, user=user)

    @mcp.tool()
    @_audited("create_incident")
    async def create_incident(title: str, severity: str, impact: str | None = None) -> dict:
        """Create a new incident. severity must be one of sev1/sev2/sev3/sev4.
        Requires an active subscription -- or, for a brand-new account,
        this is allowed to be the one free incident, same as the product's
        own paywall."""
        database = get_database()
        user = require_mcp_active_subscription_or_free_slot()
        payload = postmortem_routes.IncidentCreate(title=title, severity=severity, impact=impact)
        # _create_incident, not create_incident -- the latter is the
        # REST route itself, which no longer accepts source at all (see
        # its own docstring: that was spoofable via a REST client
        # deliberately). This is a plain Python call, not an HTTP
        # request, so passing source="mcp_agent" here is trustworthy --
        # it's set by mcp_server.py's own code, never by anything a
        # caller sends.
        return await postmortem_routes._create_incident(payload, database, user, source="mcp_agent")

    @mcp.tool()
    @_audited("add_evidence")
    async def add_evidence(
        incident_id: str, occurred_at: int, source: str, summary: str, detail: str | None = None
    ) -> dict:
        """Record an evidence entry against one of the caller's own
        incidents. source must be one of alert/log/deploy/metric/
        human_note/customer_report. occurred_at is a Unix ms timestamp."""
        database = get_database()
        user = require_mcp_active_subscription_or_free_incident(incident_id)
        payload = postmortem_routes.EvidenceCreate(
            occurred_at=occurred_at, source=source, summary=summary, detail=detail
        )
        return await postmortem_routes.record_evidence(incident_id, payload, database=database, user=user)

    @mcp.tool()
    @_audited("draft_postmortem")
    async def draft_postmortem(incident_id: str) -> dict:
        """Generate a grounded AI draft from the incident's recorded
        evidence, using retrieved similar past incidents (this account's
        own history only) as non-citable reference context. Every claim
        is still cited-or-dropped -- see the grounding algorithm in
        CLAUDE.md."""
        database = get_database()
        user = require_mcp_active_subscription_or_free_incident(incident_id)
        provider = create_model_provider(settings)
        return await postmortem_routes.draft_postmortem(
            incident_id, database=database, provider=provider, user=user, settings=settings
        )

    @mcp.tool()
    @_audited("find_similar_incidents")
    async def find_similar_incidents(query: str) -> list[dict]:
        """Semantic search over the caller's own PUBLISHED postmortems
        (RAG retrieval) -- given free-text describing a new incident,
        returns the most similar past incidents' title/summary/root cause.
        Reference only, same non-citable status as the context
        draft_postmortem retrieves automatically."""
        database = get_database()
        user = current_mcp_user()
        client = get_embedding_client(settings.gemini_api_key)
        embedding = await embed_text(client, query)
        similar = await find_similar_postmortems(database, user.email, embedding, exclude_incident_id="")
        return [
            {"incident_title": item.incident_title, "summary": item.summary, "root_cause": item.root_cause}
            for item in similar
        ]

    @mcp.tool()
    @_audited("publish_postmortem")
    async def publish_postmortem(incident_id: str) -> dict:
        """Publish the incident's current draft postmortem, recording the
        caller as the named human approver. Also notifies Slack and
        creates a Linear ticket per action item, if connected (see
        get_integrations/update_integrations)."""
        database = get_database()
        user = require_mcp_active_subscription()
        # _publish_postmortem, not publish_postmortem -- see
        # create_incident's call above for why.
        return await postmortem_routes._publish_postmortem(incident_id, database, user, settings, source="mcp_agent")

    @mcp.tool()
    @_audited("get_integrations")
    async def get_integrations() -> dict:
        """The caller's own Slack/Linear connection status (never returns
        the raw webhook URL or API key -- connected/not-connected only)."""
        database = get_database()
        user = current_mcp_user()
        result = await integrations_routes.get_integrations(database=database, user=user)
        return result.model_dump()

    @mcp.tool()
    @_audited("update_integrations")
    async def update_integrations(
        slack_webhook_url: str | None = None,
        linear_api_key: str | None = None,
        linear_team_id: str | None = None,
    ) -> dict:
        """Connect or update the caller's own Slack webhook URL and/or
        Linear API key/team ID. Omit a field to leave it unchanged; pass
        an empty string to disconnect it."""
        database = get_database()
        user = current_mcp_user()
        payload = integrations_routes.IntegrationsUpdate(
            slack_webhook_url=slack_webhook_url, linear_api_key=linear_api_key, linear_team_id=linear_team_id
        )
        result = await integrations_routes.update_integrations(payload, database=database, user=user)
        return result.model_dump()

    return mcp
