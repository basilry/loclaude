"""OpenAI-compatible /v1/chat/completions 엔진. ollama, vllm 등 로컬 서버용."""

from __future__ import annotations

import json
import os
import time
from typing import AsyncIterator

import httpx

from core.types import EventType, Message, StreamEvent, TokenUsage


class OpenAICompatEngine:
    """OpenAI /v1/chat/completions 호환 범용 어댑터."""

    provider_name: str = "openai-compat"

    def __init__(
        self,
        model: str = "default",
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
        timeout: float = 300,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers,
        )

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
        payload = self._build_payload(messages, system, temperature, max_tokens, stream=False)
        t0 = time.monotonic()
        r = await self._client.post("/v1/chat/completions", json=payload)
        elapsed_ns = int((time.monotonic() - t0) * 1e9)

        if r.status_code != 200:
            raise RuntimeError(f"OpenAI-compat {r.status_code}: {r.text[:500]}")

        data = r.json()
        content = data["choices"][0]["message"].get("content", "")
        u = data.get("usage", {})
        completion_tokens = u.get("completion_tokens", 0)
        usage = TokenUsage(
            prompt_tokens=u.get("prompt_tokens", 0),
            completion_tokens=completion_tokens,
            total_tokens=u.get("total_tokens", 0),
            eval_count=completion_tokens,
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
        payload = self._build_payload(messages, system, temperature, max_tokens, stream=True)
        t0 = time.monotonic()
        token_count = 0

        async with self._client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if token:
                    token_count += 1
                    yield StreamEvent(type=EventType.TEXT_DELTA, data=token)

        elapsed_ns = int((time.monotonic() - t0) * 1e9)
        usage = TokenUsage(eval_count=token_count, eval_duration_ns=elapsed_ns)
        yield StreamEvent(type=EventType.MESSAGE_STOP, data=usage)

    # -- Internal --

    def _build_payload(self, messages, system, temperature, max_tokens, *, stream) -> dict:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        for m in messages:
            msgs.append(m.to_openai())
        return {
            "model": self.model,
            "messages": msgs,
            "stream": stream,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
