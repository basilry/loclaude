"""Engine protocol -- 모든 LLM 엔진이 구현해야 할 인터페이스."""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from core.types import Message, StreamEvent, TokenUsage


@runtime_checkable
class EngineProtocol(Protocol):
    """LLM 엔진 공통 프로토콜."""

    provider_name: str
    model: str
    base_url: str

    async def chat(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, TokenUsage]:
        """Non-streaming chat. Returns (content, usage)."""
        ...

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming chat. Yields StreamEvent."""
        ...

    async def ping(self) -> bool:
        """Health check."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        ...
