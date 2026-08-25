import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.v1.auth import router as auth_router
from .api.v1.bank_alerts import router as bank_alerts_router
from .api.v1.billing import router as billing_router
from .api.v1.founder import router as founder_router
from .api.v1.integrations import router as integrations_router
from .api.v1.postmortems import router as postmortems_router
from .database import Database
from .mcp_server import MCPBearerAuthMiddleware, build_mcp_server
from .settings import get_settings

logger = logging.getLogger("postmortem_ai")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
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

    app = FastAPI(title="PostMortem AI", lifespan=lifespan)
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
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    app.include_router(auth_router)
    app.include_router(bank_alerts_router)
    app.include_router(billing_router)
    app.include_router(founder_router)
    app.include_router(integrations_router)
    app.include_router(postmortems_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
