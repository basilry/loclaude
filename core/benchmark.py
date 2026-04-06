"""Local model benchmark runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.engines.base import EngineProtocol
from core.stream_capture import collect_stream
from core.types import Message, Role


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
    first_token_seen: bool = False
    timed_out: bool = False
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
            "first_token_seen": self.first_token_seen,
            "timed_out": self.timed_out,
            "error": self.error,
            "timestamp": self.timestamp,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _count_tokens_approx(text: str) -> int:
    """Rough token count: split by whitespace + CJK char count."""
    ascii_tokens = len(text.split())
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\uac00" <= c <= "\ud7a3")
    return ascii_tokens + cjk_chars


async def run_benchmark_case(
    engine: EngineProtocol, case: BenchmarkCase
) -> BenchmarkResult:
    """단일 벤치마크 케이스 실행. collect_stream으로 TTFT/latency/tok_per_sec 측정."""
    messages = [Message(role=Role.USER, content=case.prompt)]

    capture = await collect_stream(
        engine,
        messages,
        temperature=0.3,
        max_tokens=2048,
        timeout_sec=case.timeout_sec,
    )

    first_token_seen = capture.first_token_ms is not None
    ttft_ms = capture.first_token_ms or 0.0

    if capture.error and not capture.timed_out:
        return BenchmarkResult(
            case_id=case.id,
            provider=engine.provider_name,
            model=engine.model,
            success=False,
            ttft_ms=ttft_ms,
            total_latency_ms=capture.total_ms,
            tok_per_sec=0.0,
            tokens_generated=0,
            tool_call_parsed=False,
            first_token_seen=first_token_seen,
            timed_out=False,
            error=capture.error,
        )

    tokens_generated = _count_tokens_approx(capture.text)
    elapsed_sec = capture.total_ms / 1000
    tok_per_sec = tokens_generated / elapsed_sec if elapsed_sec > 0 else 0.0

    tool_ok = (
        case.expected_tool in capture.tool_names
        if case.expected_tool else True
    )
    keywords_ok = all(
        kw.lower() in capture.text.lower() for kw in case.expected_keywords
    )
    success = tool_ok and keywords_ok and not capture.timed_out

    return BenchmarkResult(
        case_id=case.id,
        provider=engine.provider_name,
        model=engine.model,
        success=success,
        ttft_ms=ttft_ms,
        total_latency_ms=capture.total_ms,
        tok_per_sec=tok_per_sec,
        tokens_generated=tokens_generated,
        tool_call_parsed=tool_ok,
        first_token_seen=first_token_seen,
        timed_out=capture.timed_out,
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
