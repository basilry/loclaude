"""Evaluation framework -- LLM 엔진의 출력 품질을 검증하는 테스트 케이스 실행."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.engines.base import EngineProtocol
from core.stream_capture import collect_stream
from core.types import Message, Role

logger = logging.getLogger(__name__)


@dataclass
class EvalCase:
    id: str
    name: str
    prompt: str
    expected_output_contains: list[str] = field(default_factory=list)
    expected_tool_calls: list[str] = field(default_factory=list)
    max_turns: int = 3
    timeout_sec: float = 60.0

    @classmethod
    def from_dict(cls, d: dict) -> EvalCase:
        return cls(
            id=d["id"],
            name=d["name"],
            prompt=d["prompt"],
            expected_output_contains=d.get("expected_output_contains", []),
            expected_tool_calls=d.get("expected_tool_calls", []),
            max_turns=d.get("max_turns", 3),
            timeout_sec=d.get("timeout_sec", 60.0),
        )

    @classmethod
    def load_suite(cls, path: str | Path) -> list[EvalCase]:
        with open(path) as f:
            data = json.load(f)
        cases = data if isinstance(data, list) else data.get("cases", [])
        return [cls.from_dict(c) for c in cases]


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    actual_output: str
    expected_matches: dict[str, bool]
    tool_calls_made: list[str]
    duration_ms: float
    tool_assertion_passed: bool = True
    timeout_triggered: bool = False
    first_token_seen: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "actual_output": self.actual_output,
            "expected_matches": self.expected_matches,
            "tool_calls_made": self.tool_calls_made,
            "duration_ms": self.duration_ms,
            "tool_assertion_passed": self.tool_assertion_passed,
            "timeout_triggered": self.timeout_triggered,
            "first_token_seen": self.first_token_seen,
            "error": self.error,
        }


async def run_eval_case(engine: EngineProtocol, case: EvalCase) -> EvalResult:
    """단일 eval 케이스를 실행하고 결과를 반환."""
    messages = [Message(role=Role.USER, content=case.prompt)]

    capture = await collect_stream(
        engine,
        messages,
        temperature=0.3,
        max_tokens=2048,
        timeout_sec=case.timeout_sec,
    )

    if capture.error and not capture.timed_out:
        logger.error("Eval case %s failed: %s", case.id, capture.error)
        return EvalResult(
            case_id=case.id,
            passed=False,
            actual_output=capture.text,
            expected_matches={kw: False for kw in case.expected_output_contains},
            tool_calls_made=capture.tool_names,
            duration_ms=capture.total_ms,
            tool_assertion_passed=False,
            timeout_triggered=False,
            first_token_seen=capture.first_token_ms is not None,
            error=capture.error,
        )

    output_lower = capture.text.lower()
    expected_matches = {
        kw: kw.lower() in output_lower
        for kw in case.expected_output_contains
    }

    # tool call assertion: 모든 expected_tool_calls가 실제 tool_names에 존재하는지
    tool_assertion_passed = all(
        t in capture.tool_names for t in case.expected_tool_calls
    ) if case.expected_tool_calls else True

    all_keywords_found = all(expected_matches.values()) if expected_matches else True
    passed = all_keywords_found and tool_assertion_passed and not capture.timed_out

    return EvalResult(
        case_id=case.id,
        passed=passed,
        actual_output=capture.text,
        expected_matches=expected_matches,
        tool_calls_made=capture.tool_names,
        duration_ms=capture.total_ms,
        tool_assertion_passed=tool_assertion_passed,
        timeout_triggered=capture.timed_out,
        first_token_seen=capture.first_token_ms is not None,
        error=capture.error,
    )


async def run_eval_suite(
    engine: EngineProtocol,
    cases: list[EvalCase],
) -> list[EvalResult]:
    """여러 eval 케이스를 순차 실행."""
    results: list[EvalResult] = []
    for case in cases:
        logger.info("Running eval: %s (%s)", case.name, case.id)
        result = await run_eval_case(engine, case)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info("  %s (%.0fms)", status, result.duration_ms)
    return results


def generate_eval_report(results: list[EvalResult]) -> str:
    """결과를 markdown 형식 리포트로 생성."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    lines = [
        "# Eval Report",
        "",
        f"**Total**: {total} | **Passed**: {passed} | **Failed**: {failed}",
        "",
        "| Case ID | Passed | Duration | Keywords | Tools OK | Timeout | TTFT | Error |",
        "|---------|--------|----------|----------|----------|---------|------|-------|",
    ]

    for r in results:
        kw_summary = ", ".join(
            f"{k}:{'Y' if v else 'N'}" for k, v in r.expected_matches.items()
        )
        err = r.error[:50] if r.error else "-"
        lines.append(
            f"| {r.case_id} | {'Y' if r.passed else 'N'} "
            f"| {r.duration_ms:.0f}ms | {kw_summary or '-'} "
            f"| {'Y' if r.tool_assertion_passed else 'N'} "
            f"| {'Y' if r.timeout_triggered else 'N'} "
            f"| {'Y' if r.first_token_seen else 'N'} | {err} |"
        )

    lines.append("")
    total_ms = sum(r.duration_ms for r in results)
    lines.append(f"**Total duration**: {total_ms:.0f}ms")

    if failed > 0:
        lines.append("")
        lines.append("## Failed Cases")
        lines.append("")
        for r in results:
            if not r.passed:
                lines.append(f"### {r.case_id}")
                if r.error:
                    lines.append(f"**Error**: {r.error}")
                missed = [k for k, v in r.expected_matches.items() if not v]
                if missed:
                    lines.append(f"**Missing keywords**: {', '.join(missed)}")
                lines.append(f"**Output** (truncated):\n```\n{r.actual_output[:500]}\n```")
                lines.append("")

    return "\n".join(lines)
