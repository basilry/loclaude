"""Shared stream capture -- engine.chat_stream 결과를 수집하고 timeout을 강제."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from core.engines.base import EngineProtocol
from core.types import EventType, Message, StreamEvent


@dataclass
class StreamCapture:
    events: list[StreamEvent] = field(default_factory=list)
    text: str = ""
    tool_names: list[str] = field(default_factory=list)
    first_token_ms: float | None = None
    total_ms: float = 0.0
    timed_out: bool = False
    error: str | None = None


def extract_tool_names(events: list[StreamEvent]) -> list[str]:
    names: list[str] = []
    for ev in events:
        if ev.type == EventType.TOOL_USE and ev.data is not None:
            name = getattr(ev.data, "name", None) or (
                ev.data if isinstance(ev.data, str) else None
            )
            if name:
                names.append(name)
    return names


def collect_text(events: list[StreamEvent]) -> str:
    parts: list[str] = []
    for ev in events:
        if ev.type == EventType.TEXT_DELTA and isinstance(ev.data, str):
            parts.append(ev.data)
    return "".join(parts)


async def collect_stream(
    engine: EngineProtocol,
    messages: list[Message],
    *,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout_sec: float = 60.0,
) -> StreamCapture:
    capture = StreamCapture()
    t_start = time.perf_counter()

    async def _consume() -> None:
        first_token_seen = False
        async for event in engine.chat_stream(
            messages,
            system=system or None,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            capture.events.append(event)

            if event.type == EventType.TEXT_DELTA and not first_token_seen:
                capture.first_token_ms = (time.perf_counter() - t_start) * 1000
                first_token_seen = True

            if event.type == EventType.ERROR:
                capture.error = str(event.data)
                return

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        capture.timed_out = True
    except Exception as exc:
        capture.error = str(exc)

    capture.total_ms = (time.perf_counter() - t_start) * 1000
    capture.text = collect_text(capture.events)
    capture.tool_names = extract_tool_names(capture.events)
    return capture
