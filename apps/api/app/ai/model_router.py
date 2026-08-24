from ..settings import Settings
from .gemini_provider import GeminiProvider
from .provider import ModelProvider


def create_model_provider(settings: Settings) -> ModelProvider:
    return GeminiProvider(api_key=settings.gemini_api_key, default_model=settings.gemini_model)
