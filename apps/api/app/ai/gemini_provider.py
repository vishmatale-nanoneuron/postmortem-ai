from google import genai
from google.genai import types

from .provider import ModelRequest


class GeminiProvider:
    """Real ModelProvider implementation calling the Gemini API.

    Requires a real GEMINI_API_KEY (see Settings) -- there is no fallback to
    a fabricated/mocked response in production code. Tests use FakeProvider
    (apps/api/tests/test_postmortem_routes.py) instead of this class, so no
    live API key is needed to run the test suite.
    """

    name = "gemini"

    def __init__(self, api_key: str, default_model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._default_model = default_model

    async def complete(self, request: ModelRequest) -> str:
        response = await self._client.aio.models.generate_content(
            model=request.model or self._default_model,
            contents=[message.content for message in request.messages],
            config=types.GenerateContentConfig(
                system_instruction=request.system,
                max_output_tokens=request.max_tokens,
                temperature=request.temperature,
            ),
        )
        text = response.text
        if text is None:
            raise ValueError("Gemini returned no text content")
        return text
