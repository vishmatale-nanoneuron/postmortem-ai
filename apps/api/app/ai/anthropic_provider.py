from anthropic import AsyncAnthropic

from .provider import ModelRequest


class AnthropicProvider:
    """Real ModelProvider implementation calling the Anthropic API.

    Requires a real ANTHROPIC_API_KEY (see Settings) -- there is no fallback
    to a fabricated/mocked response in production code. Tests use
    FakeProvider (apps/api/tests/test_postmortem_routes.py) instead of this
    class, so no live API key is needed to run the test suite.
    """

    name = "anthropic"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = default_model

    async def complete(self, request: ModelRequest) -> str:
        response = await self._client.messages.create(
            model=request.model or self._default_model,
            system=request.system,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=[{"role": message.role, "content": message.content} for message in request.messages],
        )
        return "".join(block.text for block in response.content if block.type == "text")
