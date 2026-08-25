"""A real circuit breaker around the drafting model provider -- classic
three-state machine (closed/open/half-open), not just a retry loop.

Scope, stated honestly: this backend runs as Vercel serverless functions
with no shared process memory across instances or cold starts (the same
constraint documented for login rate limiting and AI-run monitoring
elsewhere in this codebase) -- so this breaker's state lives in one
process only. It does not coordinate across concurrent invocations. What
it DOES give, for free, within a single warm instance handling several
requests in a row: once Gemini has failed repeatedly, further calls fail
fast (no network round-trip, no waiting for a timeout) until a cooldown
elapses, instead of hammering an already-failing provider on every
request that instance happens to serve.
"""

import time
from dataclasses import dataclass, field

from .provider import ModelProvider, ModelRequest, ModelResponse


class CircuitOpenError(RuntimeError):
    """Raised instead of calling the wrapped provider while the circuit is
    open -- callers should treat this distinctly from a single failed
    call (e.g. a 503 rather than a 502): the provider isn't just erroring
    once, it's being deliberately avoided for a cooldown period."""


@dataclass
class CircuitBreakerProvider:
    """Wraps a ModelProvider. CLOSED (normal) -> after
    `failure_threshold` consecutive failures -> OPEN (fails fast, no call
    reaches the wrapped provider) -> after `cooldown_seconds` -> HALF_OPEN
    (exactly one trial call is allowed through) -> success closes the
    circuit and resets the failure count; failure reopens it and restarts
    the cooldown."""

    wrapped: ModelProvider
    failure_threshold: int = 5
    cooldown_seconds: float = 30.0

    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _half_open_trial_in_flight: bool = field(default=False, init=False)

    @property
    def name(self) -> str:
        return self.wrapped.name

    @property
    def model_name(self) -> str:
        return self.wrapped.model_name

    def _state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at >= self.cooldown_seconds:
            return "half_open"
        return "open"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        state = self._state()

        if state == "open":
            raise CircuitOpenError(
                f"Circuit open for {self.wrapped.name} after {self._consecutive_failures} consecutive "
                f"failures -- retry after the cooldown."
            )

        if state == "half_open":
            if self._half_open_trial_in_flight:
                # A concurrent request already claimed the one trial slot
                # -- fail fast rather than let every concurrent request
                # pile onto a provider that's still being tested.
                raise CircuitOpenError(f"Circuit half-open for {self.wrapped.name} -- a trial call is already in flight.")
            self._half_open_trial_in_flight = True
            try:
                response = await self.wrapped.complete(request)
            except Exception:
                self._opened_at = time.monotonic()
                raise
            else:
                self._consecutive_failures = 0
                self._opened_at = None
                return response
            finally:
                self._half_open_trial_in_flight = False

        # state == "closed"
        try:
            response = await self.wrapped.complete(request)
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_at = time.monotonic()
            raise
        else:
            self._consecutive_failures = 0
            return response
