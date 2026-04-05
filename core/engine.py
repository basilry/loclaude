"""MLX LM Server 엔진. OpenAI 호환 /v1/chat/completions API 사용."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import AsyncIterator

import httpx

from core.types import (
    EventType, Message, StreamEvent,
    ToolCall, TokenUsage,
)


class MLXEngine:
    """MLX LM Server /v1/chat/completions 래퍼."""

    DEFAULT_MODEL = "BeastCode/Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-4bit"

    def __init__(
        self,
        model: str | None = None,
        base_url: str = "http://localhost:8080",
        timeout: float = 300,
    ):
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def close(self):
        await self._client.aclose()

    # -- Health check --

    async def ping(self) -> dict:
        r = await self._client.get("/v1/models")
        data = r.json()
        return {"version": "mlx", "models": len(data.get("data", []))}

    async def find_model(self) -> str | None:
        """로드된 모델 중 호환 모델 탐색."""
        r = await self._client.get("/v1/models")
        models = [m["id"] for m in r.json().get("data", [])]
        if self.model in models:
            return self.model
        for name in models:
            if "qwen3.5" in name.lower():
                return name
        return models[0] if models else None

    # -- Non-streaming chat --

    async def chat(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple[str, str, list[ToolCall], TokenUsage]:
        """동기 완료. Returns (content, thinking, tool_calls, usage)."""
        payload = self._build_payload(
            messages, system=system, temperature=temperature,
            max_tokens=max_tokens, stream=False,
        )
        t0 = time.monotonic()
        r = await self._client.post("/v1/chat/completions", json=payload)
        elapsed_ns = int((time.monotonic() - t0) * 1e9)

        if r.status_code != 200:
            body = r.text[:500]
            raise RuntimeError(
                f"MLX /v1/chat/completions {r.status_code}: {body}"
            )
        data = r.json()

        raw_content = data["choices"][0]["message"].get("content", "")
        thinking, content = self._extract_thinking(raw_content)
        tool_calls = self._extract_tool_calls(content)

        u = data.get("usage", {})
        completion_tokens = u.get("completion_tokens", 0)
        usage = TokenUsage(
            prompt_tokens=u.get("prompt_tokens", 0),
            completion_tokens=completion_tokens,
            total_tokens=u.get("total_tokens", 0),
            eval_count=completion_tokens,
            eval_duration_ns=elapsed_ns,
        )
        return content, thinking, tool_calls, usage

    # -- Streaming chat --

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """SSE 스트리밍 -- StreamEvent 단위로 yield."""
        payload = self._build_payload(
            messages, system=system, temperature=temperature,
            max_tokens=max_tokens, stream=True,
        )

        full_content = ""
        in_thinking = False
        token_count = 0
        t0 = time.monotonic()

        async with self._client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                # SSE format: "data: {...}" or "data: [DONE]"
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()

                if data_str == "[DONE]":
                    # 완료 시 tool call 파싱
                    _, clean = self._extract_thinking(full_content)
                    tool_calls = self._extract_tool_calls(clean)
                    for tc in tool_calls:
                        yield StreamEvent(type=EventType.TOOL_USE, data=tc)

                    elapsed_ns = int((time.monotonic() - t0) * 1e9)
                    usage = TokenUsage(
                        eval_count=token_count,
                        eval_duration_ns=elapsed_ns,
                    )
                    yield StreamEvent(type=EventType.MESSAGE_STOP, data=usage)
                    return

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")

                if token:
                    token_count += 1
                    full_content += token

                    # <think> 태그 감지 및 분리
                    if "<think>" in token:
                        in_thinking = True
                        before = token.split("<think>")[0]
                        if before:
                            yield StreamEvent(type=EventType.TEXT_DELTA, data=before)
                        continue
                    elif "</think>" in token:
                        in_thinking = False
                        after = token.split("</think>")[-1]
                        if after:
                            yield StreamEvent(type=EventType.TEXT_DELTA, data=after)
                        continue

                    if in_thinking:
                        yield StreamEvent(type=EventType.THINKING_DELTA, data=token)
                    else:
                        yield StreamEvent(type=EventType.TEXT_DELTA, data=token)

    # -- Internal --

    def _build_payload(
        self, messages, *, system, temperature, max_tokens, stream,
    ) -> dict:
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

    @staticmethod
    def _extract_thinking(text: str) -> tuple[str, str]:
        pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
        parts = pattern.findall(text)
        clean = pattern.sub("", text).strip()
        return "\n".join(parts).strip(), clean

    @staticmethod
    def _extract_tool_calls(text: str) -> list[ToolCall]:
        """JSON tool call 블록 추출."""
        calls = []
        # ```json 블록
        for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
            calls.extend(_try_parse_tool_call(block))
        if calls:
            return calls
        # 인라인 JSON
        for match in _find_json_objects(text):
            calls.extend(_try_parse_tool_call(match))
        return calls


def _find_json_objects(text: str) -> list[str]:
    """텍스트에서 중첩 braces를 고려해 JSON 객체 후보를 추출."""
    results = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            start = i
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i+1]
                        if '"tool"' in candidate or '"name"' in candidate:
                            results.append(candidate)
                        break
                i += 1
        i += 1
    return results


def _try_parse_tool_call(text: str) -> list[ToolCall]:
    """JSON 텍스트에서 ToolCall 파싱 시도."""
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return []

    results = []
    items = parsed if isinstance(parsed, list) else [parsed]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("tool") or item.get("name")
        if not name:
            continue
        args = item.get("args") or item.get("input") or item.get("arguments") or {}
        results.append(ToolCall(
            id=item.get("id", uuid.uuid4().hex[:8]),
            name=name,
            args=args,
        ))
    return results
