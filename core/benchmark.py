"""Local model benchmark runner."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.engines.base import EngineProtocol
from core.types import EventType, Message, Role, StreamEvent


@dataclass
class BenchmarkCase:
    id: str
    name: str
    prompt: str
    expected_tool: str | None = None
    expected_keywords: list[str] = field(default_factory=list)
    timeout_sec: float = 60.0


@dataclass
class BenchmarkResult:
    case_id: str
    provider: str
    model: str
    success: bool
    ttft_ms: float
    total_latency_ms: float
    tok_per_sec: float
    tokens_generated: int
    tool_call_parsed: bool
    error: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
            "ttft_ms": round(self.ttft_ms, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "tok_per_sec": round(self.tok_per_sec, 2),
            "tokens_generated": self.tokens_generated,
            "tool_call_parsed": self.tool_call_parsed,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _check_tool_call(events: list[StreamEvent], expected_tool: str | None) -> bool:
    """tool_use 이벤트에서 expected_tool 매칭 확인."""
    if expected_tool is None:
        return True
    for ev in events:
        if ev.type == EventType.TOOL_USE and ev.data is not None:
            if hasattr(ev.data, "name") and ev.data.name == expected_tool:
                return True
    return False


def _check_keywords(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return all(kw.lower() in lower for kw in keywords)


def _count_tokens_approx(text: str) -> int:
    """Rough token count: split by whitespace + CJK char count."""
    ascii_tokens = len(text.split())
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\uac00" <= c <= "\ud7a3")
    return ascii_tokens + cjk_chars


async def run_benchmark_case(
    engine: EngineProtocol, case: BenchmarkCase
) -> BenchmarkResult:
    """단일 벤치마크 케이스 실행. chat_stream으로 TTFT/latency/tok_per_sec 측정."""
    messages = [Message(role=Role.USER, content=case.prompt)]
    collected_events: list[StreamEvent] = []
    collected_text = ""
    ttft_ms = 0.0
    first_token_received = False

    t_start = time.perf_counter()

    try:
        async for event in engine.chat_stream(messages, temperature=0.3, max_tokens=2048):
            collected_events.append(event)

            if event.type == EventType.TEXT_DELTA and not first_token_received:
                ttft_ms = (time.perf_counter() - t_start) * 1000
                first_token_received = True

            if event.type == EventType.TEXT_DELTA and isinstance(event.data, str):
                collected_text += event.data

            if event.type == EventType.ERROR:
                raise RuntimeError(event.data)

    except Exception as exc:
        total_ms = (time.perf_counter() - t_start) * 1000
        return BenchmarkResult(
            case_id=case.id,
            provider=engine.provider_name,
            model=engine.model,
            success=False,
            ttft_ms=ttft_ms,
            total_latency_ms=total_ms,
            tok_per_sec=0.0,
            tokens_generated=0,
            tool_call_parsed=False,
            error=str(exc),
        )

    total_ms = (time.perf_counter() - t_start) * 1000
    tokens_generated = _count_tokens_approx(collected_text)
    elapsed_sec = total_ms / 1000
    tok_per_sec = tokens_generated / elapsed_sec if elapsed_sec > 0 else 0.0

    tool_ok = _check_tool_call(collected_events, case.expected_tool)
    keywords_ok = _check_keywords(collected_text, case.expected_keywords)
    success = tool_ok and keywords_ok

    return BenchmarkResult(
        case_id=case.id,
        provider=engine.provider_name,
        model=engine.model,
        success=success,
        ttft_ms=ttft_ms,
        total_latency_ms=total_ms,
        tok_per_sec=tok_per_sec,
        tokens_generated=tokens_generated,
        tool_call_parsed=tool_ok,
    )


async def run_benchmark_suite(
    engine: EngineProtocol, cases: list[BenchmarkCase]
) -> list[BenchmarkResult]:
    """벤치마크 케이스 목록을 순회 실행하고 결과 리스트 반환."""
    results: list[BenchmarkResult] = []
    for case in cases:
        result = await run_benchmark_case(engine, case)
        results.append(result)
    return results


def load_cases_from_json(path: str) -> list[BenchmarkCase]:
    """JSON 파일에서 BenchmarkCase 목록 로드."""
    with open(path) as f:
        data = json.load(f)
    return [
        BenchmarkCase(
            id=item["id"],
            name=item["name"],
            prompt=item["prompt"],
            expected_tool=item.get("expected_tool"),
            expected_keywords=item.get("expected_keywords", []),
            timeout_sec=item.get("timeout_sec", 60.0),
        )
        for item in data
    ]
