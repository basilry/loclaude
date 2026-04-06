"""OpenAI Responses API 엔진. httpx 기반, SDK 의존성 없음."""

from __future__ import annotations

import json
import os
import time
from typing import AsyncIterator

import httpx

from core.types import EventType, Message, StreamEvent, TokenUsage


class OpenAIResponsesEngine:
    """OpenAI Responses API (/v1/responses) 래퍼."""

    provider_name: str = "openai"

    def __init__(
        self,
        model: str = "gpt-4o",
        base_url: str = "https://api.openai.com",
        api_key: str | None = None,
        timeout: float = 120,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            r = await self._client.get("/v1/models")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    # -- Non-streaming --

    async def chat(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, TokenUsage]:
        payload = self._build_request(messages, system, temperature, max_tokens, stream=False)
        t0 = time.monotonic()
        r = await self._client.post("/v1/responses", json=payload)
        elapsed_ns = int((time.monotonic() - t0) * 1e9)

        if r.status_code != 200:
            raise RuntimeError(f"OpenAI /v1/responses {r.status_code}: {r.text[:500]}")

        data = r.json()
        content = self._parse_response_output(data)
        u = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=u.get("input_tokens", 0),
            completion_tokens=u.get("output_tokens", 0),
            total_tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0),
            eval_count=u.get("output_tokens", 0),
            eval_duration_ns=elapsed_ns,
        )
        return content, usage

    # -- Streaming --

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._build_request(messages, system, temperature, max_tokens, stream=True)
        t0 = time.monotonic()
        token_count = 0

        async with self._client.stream("POST", "/v1/responses", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                for se in self._stream_to_events(event):
                    if se.type == EventType.TEXT_DELTA:
                        token_count += 1
                    yield se

        elapsed_ns = int((time.monotonic() - t0) * 1e9)
        usage = TokenUsage(eval_count=token_count, eval_duration_ns=elapsed_ns)
        yield StreamEvent(type=EventType.MESSAGE_STOP, data=usage)

    # -- Internal --

    def _build_request(
        self, messages, system, temperature, max_tokens, *, stream,
    ) -> dict:
        input_items = []
        if system:
            input_items.append({"role": "developer", "content": system})
        for m in messages:
            input_items.append({"role": m.role.value, "content": m.content})

        return {
            "model": self.model,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "stream": stream,
        }

    @staticmethod
    def _parse_response_output(data: dict) -> str:
        """Extract text content from Responses API output."""
        output = data.get("output", [])
        parts = []
        for item in output:
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        parts.append(c.get("text", ""))
        return "".join(parts)

    @staticmethod
    def _stream_to_events(event: dict) -> list[StreamEvent]:
        """Convert a Responses API SSE event to StreamEvents."""
        events = []
        etype = event.get("type", "")

        if etype == "response.output_text.delta":
            delta = event.get("delta", "")
            if delta:
                events.append(StreamEvent(type=EventType.TEXT_DELTA, data=delta))

        return events
