from functools import lru_cache

from ..settings import Settings
from .circuit_breaker import CircuitBreakerProvider
from .claude_provider import ClaudeProvider
from .fallback_provider import FallbackProvider
from .gemini_provider import GeminiProvider
from .provider import ModelProvider


@lru_cache
def _shared_circuit_breaker(api_key: str, default_model: str) -> CircuitBreakerProvider:
    # Cached per (api_key, model) -- in practice there's only ever one
    # real combination in a given deployment, but keying on both avoids
    # silently sharing breaker state across a future multi-model setup.
    # Caching (rather than constructing fresh per request, which
    # get_model_provider's Depends() would otherwise do) is what makes the
    # breaker's state persist across requests within one warm process --
    # a fresh instance every call would always read as "closed" and the
    # breaker would never do anything.
    return CircuitBreakerProvider(wrapped=GeminiProvider(api_key=api_key, default_model=default_model))


@lru_cache
def _shared_claude_circuit_breaker(api_key: str, default_model: str) -> CircuitBreakerProvider:
    # Same caching reasoning as _shared_circuit_breaker above, kept as a
    # separate cache (not reusing that function) so a Gemini and a Claude
    # breaker with coincidentally equal (api_key, model) tuples -- never
    # realistic since the keys come from different providers, but not
    # guaranteed distinct by type alone -- can never collide in the cache.
    return CircuitBreakerProvider(wrapped=ClaudeProvider(api_key=api_key, default_model=default_model))


@lru_cache
def _shared_fallback_provider(
    gemini_api_key: str, gemini_model: str, anthropic_api_key: str, anthropic_model: str
) -> FallbackProvider:
    return FallbackProvider(
        primary=_shared_circuit_breaker(gemini_api_key, gemini_model),
        secondary=_shared_claude_circuit_breaker(anthropic_api_key, anthropic_model),
    )


def create_model_provider(settings: Settings) -> ModelProvider:
    # Gemini, else Claude -- see ai/fallback_provider.py. Claude is only
    # ever reached when ANTHROPIC_API_KEY is configured; unset (the
    # default), behavior is exactly what it was before this fallback
    # existed -- Gemini alone, same circuit breaker, same everything.
    if settings.anthropic_api_key:
        return _shared_fallback_provider(
            settings.gemini_api_key, settings.gemini_model, settings.anthropic_api_key, settings.anthropic_model
        )
    return _shared_circuit_breaker(settings.gemini_api_key, settings.gemini_model)
