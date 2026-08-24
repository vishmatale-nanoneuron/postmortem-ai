from ..settings import Settings
from .anthropic_provider import AnthropicProvider
from .provider import ModelProvider


def create_model_provider(settings: Settings) -> ModelProvider:
    return AnthropicProvider(api_key=settings.anthropic_api_key, default_model=settings.anthropic_model)
