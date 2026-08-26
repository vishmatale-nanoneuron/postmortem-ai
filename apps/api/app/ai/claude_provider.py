from anthropic import AsyncAnthropic

from .provider import ModelRequest, ModelResponse


class ClaudeProvider:
    """Real ModelProvider implementation calling the Anthropic API --
    exists purely as a fallback (see model_router.py): Gemini is the
    primary provider everywhere in this app, this is only ever reached
    when Gemini's own call fails or its circuit breaker is open. Requires
    a real ANTHROPIC_API_KEY (see Settings) -- there is no fallback to a
    fabricated/mocked response in production code, same stance as
    GeminiProvider. Tests use FakeProvider instead of either real class.
    """

    name = "claude"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self.model_name = default_model

    async def complete(self, request: ModelRequest) -> ModelResponse:
        response = await self._client.messages.create(
            model=request.model or self.model_name,
            system=request.system,
            messages=[{"role": message.role, "content": message.content} for message in request.messages],
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise ValueError("Claude returned no text content")
        output_tokens = response.usage.output_tokens if response.usage else None
        return ModelResponse(text=text, output_tokens=output_tokens)
