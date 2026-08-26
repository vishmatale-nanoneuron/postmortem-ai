"""Pure unit tests for FallbackProvider -- no real API keys, no network.
Two FakeProviders scripted to succeed/fail on demand drive every path:
primary succeeds (never touches secondary), primary fails and secondary
rescues it, and both fail (secondary's exception propagates).
"""

import pytest
from app.ai.fallback_provider import FallbackProvider
from app.ai.provider import ModelRequest, ModelResponse

REQUEST = ModelRequest(messages=[], system="", model=None)


class FakeProvider:
    def __init__(self, name: str, should_fail: bool = False) -> None:
        self.name = name
        self.model_name = f"{name}-model"
        self.should_fail = should_fail
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError(f"{self.name} failed")
        return ModelResponse(text=f"ok from {self.name}", output_tokens=1)


@pytest.mark.asyncio
async def test_a_successful_primary_call_never_touches_the_secondary() -> None:
    primary = FakeProvider("gemini")
    secondary = FakeProvider("claude")
    provider = FallbackProvider(primary=primary, secondary=secondary)

    response = await provider.complete(REQUEST)

    assert response.text == "ok from gemini"
    assert primary.calls == 1
    assert secondary.calls == 0
    assert provider.name == "gemini"
    assert provider.model_name == "gemini-model"


@pytest.mark.asyncio
async def test_a_failed_primary_call_falls_back_to_the_secondary() -> None:
    primary = FakeProvider("gemini", should_fail=True)
    secondary = FakeProvider("claude")
    provider = FallbackProvider(primary=primary, secondary=secondary)

    response = await provider.complete(REQUEST)

    assert response.text == "ok from claude"
    assert primary.calls == 1
    assert secondary.calls == 1
    # name/model_name now report the provider that actually served the
    # call -- this is what ai_runs logging reads right after complete()
    # returns, so it must reflect reality, not just the configured primary.
    assert provider.name == "claude"
    assert provider.model_name == "claude-model"


@pytest.mark.asyncio
async def test_when_both_providers_fail_the_secondarys_exception_propagates() -> None:
    primary = FakeProvider("gemini", should_fail=True)
    secondary = FakeProvider("claude", should_fail=True)
    provider = FallbackProvider(primary=primary, secondary=secondary)

    with pytest.raises(RuntimeError, match="claude failed"):
        await provider.complete(REQUEST)

    assert primary.calls == 1
    assert secondary.calls == 1


@pytest.mark.asyncio
async def test_name_reverts_to_primary_after_a_later_successful_primary_call() -> None:
    # A FallbackProvider is reused across many requests (see model_router.py's
    # lru_cache) -- one request's fallback to secondary must not leave
    # every subsequent successful primary call reporting the wrong name.
    primary = FakeProvider("gemini", should_fail=True)
    secondary = FakeProvider("claude")
    provider = FallbackProvider(primary=primary, secondary=secondary)

    await provider.complete(REQUEST)
    assert provider.name == "claude"

    primary.should_fail = False
    await provider.complete(REQUEST)
    assert provider.name == "gemini"
