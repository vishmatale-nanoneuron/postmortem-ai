"""Gemini, else Claude -- a second real model provider, not just a second
model, so drafting/extraction survive a Gemini-side outage instead of
failing outright with the circuit breaker open. Only ever reaches Claude
when Gemini's own call fails (a real API error, timeout, or the circuit
breaker already open from repeated recent failures) -- Gemini stays the
primary provider in every case where it actually works.
"""

from dataclasses import dataclass, field

from .provider import ModelProvider, ModelRequest, ModelResponse


@dataclass
class FallbackProvider:
    """Wraps two ModelProviders (each typically already wrapped in its own
    CircuitBreakerProvider -- see model_router.py). complete() tries
    `primary` first; only on its failure does it try `secondary`. name/
    model_name report whichever provider actually served the most recent
    call (defaulting to `primary` before any call happens), so ai_runs
    logging (which reads provider.name/model_name right after complete()
    returns) correctly records which one really answered -- not just
    which one was configured as primary."""

    primary: ModelProvider
    secondary: ModelProvider
    _last_used: ModelProvider = field(init=False)

    def __post_init__(self) -> None:
        self._last_used = self.primary

    @property
    def name(self) -> str:
        return self._last_used.name

    @property
    def model_name(self) -> str:
        return self._last_used.model_name

    async def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            response = await self.primary.complete(request)
        except Exception:
            # Deliberately broad -- a CircuitOpenError, a real API error, a
            # timeout, an unreadable response (GeminiProvider's own
            # ValueError) all mean the same thing here: primary didn't
            # produce a usable response, try the fallback. If secondary
            # also fails, that exception propagates as-is -- the caller's
            # existing error handling (postmortems.py already handles
            # CircuitOpenError, genai_errors, etc.) still applies to
            # whichever provider's exception type comes out of it.
            response = await self.secondary.complete(request)
            self._last_used = self.secondary
            return response
        else:
            self._last_used = self.primary
            return response
