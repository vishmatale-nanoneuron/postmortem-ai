"""Pure unit tests for the circuit breaker -- no database, no real model
provider. A FakeProvider is scripted to fail or succeed on demand so every
state transition (closed -> open -> half-open -> closed/open again) is
driven deterministically rather than relying on timing flakiness.
"""

import asyncio

import pytest
from app.ai.circuit_breaker import CircuitBreakerProvider, CircuitOpenError
from app.ai.provider import ModelRequest, ModelResponse

REQUEST = ModelRequest(messages=[], system="", model=None)


class FakeProvider:
    name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0
        self.should_fail = True

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("simulated provider failure")
        return ModelResponse(text="ok", output_tokens=1)


@pytest.mark.asyncio
async def test_stays_closed_below_the_failure_threshold() -> None:
    fake = FakeProvider()
    breaker = CircuitBreakerProvider(wrapped=fake, failure_threshold=3, cooldown_seconds=30)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.complete(REQUEST)

    # A third call still reaches the wrapped provider -- the circuit
    # hasn't tripped yet, so no CircuitOpenError.
    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_opens_after_the_failure_threshold_and_fails_fast() -> None:
    fake = FakeProvider()
    breaker = CircuitBreakerProvider(wrapped=fake, failure_threshold=3, cooldown_seconds=30)

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await breaker.complete(REQUEST)
    assert fake.calls == 3

    # The circuit is now open -- the next call must NOT reach the wrapped
    # provider at all (fail fast).
    with pytest.raises(CircuitOpenError):
        await breaker.complete(REQUEST)
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_a_success_resets_the_consecutive_failure_count() -> None:
    fake = FakeProvider()
    breaker = CircuitBreakerProvider(wrapped=fake, failure_threshold=3, cooldown_seconds=30)

    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)

    fake.should_fail = False
    await breaker.complete(REQUEST)  # success -- resets the count

    fake.should_fail = True
    # Two more failures shouldn't trip a threshold of 3 if the count was
    # really reset (would need a third to open).
    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    assert breaker._state() == "closed"


@pytest.mark.asyncio
async def test_half_open_trial_succeeds_and_closes_the_circuit() -> None:
    fake = FakeProvider()
    breaker = CircuitBreakerProvider(wrapped=fake, failure_threshold=1, cooldown_seconds=0.05)

    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    assert breaker._state() == "open"

    await asyncio.sleep(0.06)
    assert breaker._state() == "half_open"

    fake.should_fail = False
    result = await breaker.complete(REQUEST)
    assert result.text == "ok"
    assert breaker._state() == "closed"


@pytest.mark.asyncio
async def test_a_failed_half_open_trial_reopens_the_circuit() -> None:
    fake = FakeProvider()
    breaker = CircuitBreakerProvider(wrapped=fake, failure_threshold=1, cooldown_seconds=0.05)

    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    await asyncio.sleep(0.06)
    assert breaker._state() == "half_open"

    # Still failing -- the trial call itself fails.
    with pytest.raises(RuntimeError):
        await breaker.complete(REQUEST)
    assert breaker._state() == "open"

    # And immediately fails fast again, not another real call.
    calls_before = fake.calls
    with pytest.raises(CircuitOpenError):
        await breaker.complete(REQUEST)
    assert fake.calls == calls_before
