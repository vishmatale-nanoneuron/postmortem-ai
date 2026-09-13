import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from fastapi.concurrency import run_in_threadpool

from .api.v1.airlock import FAIL_CLOSED_PATHS
from .cqrs.request_errors import (
    MAX_NOTIFICATIONS_PER_HOUR,
    RecordErrorCommand,
    handle_record_error,
    mark_notified,
    notifications_in_last_hour,
)
from .services.email import EmailNotConfiguredError, send_founder_error_notification
from .api.v1.airlock import router as airlock_router
from .api.v1.auth import router as auth_router
from .api.v1.bank_alerts import router as bank_alerts_router
from .api.v1.billing import router as billing_router
from .api.v1.founder import router as founder_router
from .api.v1.integrations import router as integrations_router
from .api.v1.internal import router as internal_router
from .api.v1.postmortems import router as postmortems_router
from .api.v1.webhooks import router as webhooks_router
from .database import Database
from .dependencies import get_database
from .mcp_server import MCPBearerAuthMiddleware, build_mcp_server
from .settings import get_settings

logger = logging.getLogger("postmortem_ai")


# Correlation. Every response carries X-Request-ID -- the caller's own if
# they sent one (a customer's trace id), else a fresh uuid -- and the same
# id is on every log line for that request and in the body of a 500, so
# "my scan at 14:02 failed" becomes "request 7f3a... failed" and can be
# found in the platform logs in one search. Vercel also stamps
# x-vercel-id; that stays as-is alongside.
REQUEST_ID_HEADER = "X-Request-ID"


def _request_id(request: Request) -> str:
    supplied = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    # Bounded and printable: a header is untrusted input and ends up in logs.
    if supplied and len(supplied) <= 128 and supplied.isprintable():
        return supplied
    return uuid.uuid4().hex


def _operation_id(route: APIRoute) -> str:
    """Clean operationIds for generated clients: `scan`, `create_key`,
    `submit_pack_claim` -- rather than FastAPI's default
    `scan_v1_airlock_scan_post`, which becomes the method name in every
    OpenAPI-generated SDK. Names are unique per router because every route
    function already has a distinct name."""
    return route.name


async def _record_and_notify(request: Request, exc: Exception, request_id: str) -> None:
    """The error ledger (cqrs/request_errors.py) and, for a fault not seen
    today, one email to the founder. Everything here is best-effort: it
    runs inside the 500 handler, so nothing it does may raise, and a
    database that is itself the failure simply means no row this time --
    the log line above still exists."""
    try:
        database = getattr(request.app.state, "database", None)
        if database is None:
            return
        recorded = await handle_record_error(
            database,
            RecordErrorCommand(
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                error_type=type(exc).__name__,
                message=str(exc),
            ),
        )
        if recorded is None or not recorded.first_today:
            return
        if await notifications_in_last_hour(database) >= MAX_NOTIFICATIONS_PER_HOUR:
            return
        settings = get_settings()
        try:
            await run_in_threadpool(
                send_founder_error_notification,
                settings,
                error_type=type(exc).__name__,
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                message=str(exc)[:300],
                fingerprint=recorded.fingerprint,
            )
        except EmailNotConfiguredError:
            return
        await mark_notified(database, recorded.id)
    except Exception:
        logger.warning("request_error_record_failed", exc_info=True)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or _request_id(request)
    logger.exception(
        "Unhandled exception on %s %s request_id=%s", request.method, request.url.path, request_id, exc_info=exc
    )
    await _record_and_notify(request, exc, request_id)
    content: dict = {"detail": "Internal server error", "request_id": request_id}
    if request.url.path in FAIL_CLOSED_PATHS:
        # The guard's own failure is a block, and the body says so, for the
        # client that reads the body before the status code.
        content["verdict"] = "block"
    response = JSONResponse(status_code=500, content=content)
    response.headers[REQUEST_ID_HEADER] = request_id
    # A handler registered for the base Exception class is run by
    # Starlette's ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware
    # -- so CORSMiddleware never gets a chance to add its headers to this
    # response, and every unhandled 500 looks like "Failed to fetch" /
    # a CORS error to the browser instead of a readable error. Add the
    # same headers CORSMiddleware would have, by hand, only here.
    origin = request.headers.get("origin")
    if origin and origin in get_settings().cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


def create_app() -> FastAPI:
    settings = get_settings()

    # `app` is assigned below, after this closure is defined -- fine, since
    # a lambda resolves free variables at call time, and `get_database` is
    # only ever called from inside a real request (well after `app` is a
    # real FastAPI instance with `app.state.database` set by lifespan).
    mcp_server = build_mcp_server(get_database=lambda: app.state.database, settings=settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings)
        await database.open()
        app.state.database = database
        try:
            # The MCP session manager owns its own background task group;
            # mounting its ASGI app via app.mount() does NOT automatically
            # run a sub-app's own lifespan (a real Starlette/FastAPI
            # gotcha), so it's driven explicitly here, inside this app's
            # own lifespan, instead.
            async with mcp_server.session_manager.run():
                yield
        finally:
            await database.close()

    app = FastAPI(
        title="NanoNeuron API",
        version="2026.09.13",
        # Everything a generated client or a reviewer needs from the
        # document itself: who to contact, the terms the API is used
        # under, where it is served, and where the long-form reference is.
        contact={"name": "NanoNeuron", "url": "https://www.nanoneuron.ai", "email": "vish.matale@gmail.com"},
        terms_of_service="https://www.nanoneuron.ai/terms",
        servers=[{"url": "https://postmortem-ai-api.vercel.app", "description": "Production"}],
        openapi_tags=[
            {"name": "airlock", "description": "Scan, egress, keys, credits and pricing for the paid guard."},
            {"name": "auth", "description": "Register, log in, session, account erasure."},
            {"name": "billing", "description": "UPI and international-wire claims, the only payment rails."},
            {"name": "founder", "description": "Owner-only: approve claims, grant credits, business metrics."},
            {"name": "ops", "description": "Health."},
        ],
        # No custom response class: this FastAPI serialises a response_model
        # straight from pydantic-core to bytes, which is faster than routing
        # through orjson and a Python dict, and the old ORJSONResponse
        # default is deprecated for exactly that reason. Every route here
        # declares a response_model.
        generate_unique_id_function=_operation_id,
        # Keep the Authorize key across a page reload of /docs, so trying
        # the API from the browser does not mean re-pasting it every time.
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
        summary="Airlock (paid prompt-injection and exfiltration guard for AI agents) and PostMortem AI.",
        description=(
            "Airlock: `POST /v1/airlock/scan` and `POST /v1/airlock/egress` authenticate with an API key in the "
            "`X-Airlock-Key` header (or `Authorization: Bearer alk_...`) and spend one prepaid credit per call "
            "(five with `\"deep\": true`). A call with no credits is refused with **402** and nothing is scanned; "
            "a missing or invalid key is **401**; an unauthenticated flood is bounded per address with **429**. "
            "Credits are bought as packs from the dashboard over UPI or international wire and approved by hand. "
            "The audit log keeps a SHA-256 of what was scanned, never the content.\n\n"
            "PostMortem AI: evidence-grounded incident postmortems. Session-cookie authenticated."
        ),
        lifespan=lifespan,
    )
    # Outermost first: gzip wraps everything below it. Bodies under 1 KB
    # are left alone (the headers would cost more than they save).
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the session cookie to cross the frontend<->backend origin boundary
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.exception_handler(Exception)(unhandled_exception_handler)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        # No CSP here deliberately -- /docs (Swagger UI) loads its JS/CSS
        # from a CDN, so a strict script-src would break the one page on
        # this API that's actually meant to render in a browser. Everything
        # else this API returns is JSON, where these headers still matter
        # (a browser that got tricked into framing/rendering a JSON response
        # as something else) without the CSP tradeoff.
        request.state.request_id = _request_id(request)
        started = time.perf_counter()
        response = await call_next(request)
        # Correlation id back to the caller, and how long the app spent on
        # the request (Server-Timing is the standard header browsers show
        # in their network panel; customers measuring Airlock's latency
        # get the app-side number separately from their network's).
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Confirmed live in production before this fix: every route --
        # /v1/auth/me, /v1/billing/status, /v1/founder/summary included --
        # was served with Vercel's own default `Cache-Control: public,
        # max-age=0, must-revalidate` and no `Vary` header at all, since
        # nothing in this app ever set its own Cache-Control. `public` with
        # no Vary means a shared cache (a CDN, a corporate proxy) is
        # technically permitted to store and later serve one caller's
        # session-cookie-authenticated response to a different caller,
        # relying entirely on every intermediary correctly honoring
        # must-revalidate with no validator present -- not something to
        # trust platform defaults for on founder/client session data.
        # Force the unambiguous, correct policy on every response instead:
        # never cached, never shared, always fetched fresh from this
        # origin. Public, genuinely cacheable data (pricing, published
        # postmortems) is served by the Next.js frontend's own routes with
        # their own explicit revalidate windows, not this API directly, so
        # there's no real caching benefit being given up here.
        # A route may opt out only by setting its own Cache-Control first,
        # and only the two public, unauthenticated Airlock reads do
        # (/v1/airlock/pricing and /stats -- see their handlers). Everything
        # that did not say otherwise gets the safe default. Vary: Cookie is
        # set regardless, so even an opted-out response is keyed per
        # session by any cache that honours it.
        response.headers.setdefault("Cache-Control", "private, no-store, must-revalidate")
        response.headers["Vary"] = "Cookie"
        return response

    app.include_router(airlock_router)
    app.include_router(auth_router)
    app.include_router(bank_alerts_router)
    app.include_router(billing_router)
    app.include_router(founder_router)
    app.include_router(integrations_router)
    app.include_router(internal_router)
    app.include_router(postmortems_router)
    app.include_router(webhooks_router)

    @app.get("/health", tags=["ops"], summary="Liveness with a real database round-trip")
    async def health(database: Database = Depends(get_database)) -> JSONResponse:
        # A static {"status": "ok"} would have kept reporting healthy
        # straight through this project's own real db() outage (see
        # CLAUDE.md's "Resolved: db() site-wide outage") -- the actual
        # failure mode was the database being unreachable while every
        # other route 500'd. A real round-trip query is the only honest
        # signal a status page can build on.
        try:
            await database.fetch_one("SELECT 1")
        except Exception:
            logger.exception("health_check_database_unreachable")
            return JSONResponse(status_code=503, content={"status": "degraded", "database": "unreachable"})
        return JSONResponse(status_code=200, content={"status": "ok", "database": "reachable"})

    # Mounted at "/", not "/mcp" -- streamable_http_app() already mounts
    # its own handler internally at settings.streamable_http_path (default
    # "/mcp"), so mounting the whole app again at "/mcp" here would double
    # it up to "/mcp/mcp" (found via a real failed test, not by inspection).
    # This mount is added LAST so every route above still matches first;
    # only unmatched paths (i.e. "/mcp/...") fall through to it.
    app.mount("/", MCPBearerAuthMiddleware(mcp_server.streamable_http_app(), settings))

    return app


# Vercel's FastAPI framework preset requires a top-level "app" instance in
# this module (see docs/frameworks/backend/fastapi#exporting-the-fastapi-
# application) -- the --factory uvicorn flag used for local dev doesn't
# need this, but production deployment does. Safe at import time: the only
# places this module is imported are (a) uvicorn/Vercel's runtime, where
# real env vars are always present, and (b) test fixtures, which only
# import app.main lazily inside the fixture function, after
# monkeypatch.setenv() has already set every required Settings field.
app = create_app()
