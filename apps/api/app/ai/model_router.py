from functools import lru_cache

from ..settings import Settings
from .circuit_breaker import CircuitBreakerProvider
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


def create_model_provider(settings: Settings) -> ModelProvider:
    return _shared_circuit_breaker(settings.gemini_api_key, settings.gemini_model)
