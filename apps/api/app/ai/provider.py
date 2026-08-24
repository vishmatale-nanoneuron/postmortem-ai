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


class ModelProvider(Protocol):
    name: str

    async def complete(self, request: ModelRequest) -> str: ...
