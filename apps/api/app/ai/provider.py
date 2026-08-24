from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ModelRequest:
    messages: list[ModelMessage]
    system: str
    model: str | None = None
    max_tokens: int = 2_048
    temperature: float = 0.1


@dataclass(frozen=True)
class ModelResponse:
    text: str
    # None when a provider doesn't report usage (or a test double doesn't
    # bother) -- ai_runs.output_tokens is nullable for the same reason.
    output_tokens: int | None = None


class ModelProvider(Protocol):
    name: str
    model_name: str

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
