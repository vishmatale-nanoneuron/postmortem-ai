import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.v1.auth import router as auth_router
from .api.v1.postmortems import router as postmortems_router
from .database import Database
from .settings import get_settings

logger = logging.getLogger("postmortem_ai")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    database = Database(settings)
    await database.open()
    app.state.database = database
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PostMortem AI", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the session cookie to cross the frontend<->backend origin boundary
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.exception_handler(Exception)(unhandled_exception_handler)
    app.include_router(auth_router)
    app.include_router(postmortems_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
