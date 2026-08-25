"""A handler registered for the base Exception class is run by Starlette's
ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware -- so an unhandled
500 can silently come back with no CORS headers, which the browser reports
as a generic "Failed to fetch" instead of a readable error. This is the
real bug that caused exactly that report in production (a still-unmigrated
column made /v1/auth/register 500, and the frontend just saw a network
failure). Runs without a real database -- it's testing the exception path
itself, not any specific route's logic.
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_an_unhandled_exception_still_carries_cors_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/unused")
    monkeypatch.setenv("GEMINI_API_KEY", "unused")
    monkeypatch.setenv("SESSION_SECRET", "unused")
    monkeypatch.setenv("CORS_ORIGINS", "https://www.nanoneuron.ai")

    from app.dependencies import get_database
    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    application = create_app()

    def _broken_dependency() -> None:
        raise RuntimeError("simulated unhandled failure")

    application.dependency_overrides[get_database] = _broken_dependency

    # raise_app_exceptions=False -- otherwise httpx's test transport
    # re-raises the app's own unhandled exception instead of returning the
    # response ServerErrorMiddleware actually produces, which is exactly
    # the response (and its missing CORS headers) this test needs to see.
    async with AsyncClient(
        transport=ASGITransport(app=application, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/postmortems/incidents", headers={"origin": "https://www.nanoneuron.ai", "cookie": "session_token=x"}
        )

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == "https://www.nanoneuron.ai"
    assert response.headers.get("access-control-allow-credentials") == "true"
    get_settings.cache_clear()
