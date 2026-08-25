"""Pure unit tests for alerting.py -- no real webhook, no database."""

import httpx
import pytest
from app.alerting import send_alert


@pytest.mark.asyncio
async def test_a_missing_webhook_url_is_a_silent_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should never attempt a network call with no webhook URL")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)
    await send_alert(None, "should never be sent")
    assert not called


@pytest.mark.asyncio
async def test_a_configured_webhook_receives_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    received = {}

    async def fake_post(self, url, json=None, **kwargs):
        received["url"] = url
        received["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await send_alert("https://hooks.example.com/alert", "circuit breaker is open")

    assert received["url"] == "https://hooks.example.com/alert"
    assert "circuit breaker is open" in received["json"]["text"]


@pytest.mark.asyncio
async def test_a_failed_webhook_delivery_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(self, url, json=None, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    # Must swallow the failure -- an alert that can't be delivered must
    # never become an unhandled exception in the request that triggered it.
    await send_alert("https://hooks.example.com/alert", "circuit breaker is open")
