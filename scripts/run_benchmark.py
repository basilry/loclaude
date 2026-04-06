#!/usr/bin/env python3
"""Benchmark CLI: 로컬/원격 모델 성능 측정 및 리포트 생성."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# project root를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.benchmark import BenchmarkResult, load_cases_from_json, run_benchmark_suite
from core.benchmark_models import ModelCandidate, ModelMatrix
from core.engines.factory import create_engine
from core.settings import resolve_api_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run benchmark suite against LLM engines")
    p.add_argument("--provider", default=None, help="Provider: mlx, openai, openai-compat")
    p.add_argument("--model", default=None, help="Model name/path")
    p.add_argument("--base-url", default=None, help="Base URL for the engine")
    p.add_argument(
        "--suite",
        default=str(Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "benchmark_tasks.json"),
        help="Path to benchmark suite JSON",
    )
    p.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "benchmark_results"),
        help="Output directory for results",
    )
    p.add_argument("--all", action="store_true", help="Run all default model candidates")
    return p.parse_args()


def _build_candidates(args: argparse.Namespace) -> list[ModelCandidate]:
    """CLI 인자 또는 기본 매트릭스에서 후보 목록 생성."""
    if args.all:
        return ModelMatrix.default().candidates

    if args.provider and args.model:
        return [
            ModelCandidate(
                provider=args.provider,
                model=args.model,
                base_url=args.base_url or "http://localhost:8080/v1",
                description="CLI-specified model",
            )
        ]

    # 기본: MLX 로컬만
    matrix = ModelMatrix.default()
    return matrix.filter_by_provider("mlx")


def _write_jsonl(results: list[BenchmarkResult], path: Path) -> None:
    with open(path, "a") as f:
        for r in results:
            f.write(r.to_jsonl() + "\n")


def _write_markdown(
    all_results: dict[str, list[BenchmarkResult]], path: Path
) -> None:
    lines = [
        "# Benchmark Results",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    for label, results in all_results.items():
        lines.append(f"## {label}")
        lines.append("")
        lines.append(
            "| Case | Success | TTFT (ms) | Total (ms) | tok/s | Tokens | Tool OK | TTFT OK | Timeout |"
        )
        lines.append(
            "|------|---------|-----------|------------|-------|--------|---------|---------|---------|"
        )
        for r in results:
            status = "PASS" if r.success else "FAIL"
            tool = "Y" if r.tool_call_parsed else "N"
            ttft_ok = "Y" if r.first_token_seen else "N"
            tout = "Y" if r.timed_out else "N"
            lines.append(
                f"| {r.case_id} | {status} | {r.ttft_ms:.0f} | "
                f"{r.total_latency_ms:.0f} | {r.tok_per_sec:.1f} | "
                f"{r.tokens_generated} | {tool} | {ttft_ok} | {tout} |"
            )
        if results:
            avg_ttft = sum(r.ttft_ms for r in results) / len(results)
            avg_tps = sum(r.tok_per_sec for r in results) / len(results)
            pass_rate = sum(1 for r in results if r.success) / len(results) * 100
            lines.append("")
            lines.append(
                f"**Avg TTFT:** {avg_ttft:.0f}ms | "
                f"**Avg tok/s:** {avg_tps:.1f} | "
                f"**Pass rate:** {pass_rate:.0f}%"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    args = parse_args()
    cases = load_cases_from_json(args.suite)
    candidates = _build_candidates(args)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    jsonl_path = out_dir / f"benchmark_{ts}.jsonl"
    md_path = out_dir / f"benchmark_{ts}.md"

    all_results: dict[str, list[BenchmarkResult]] = {}

    for candidate in candidates:
        label = f"{candidate.provider}/{candidate.model}"
        print(f"\n--- Benchmarking: {label} ---")

        api_key = resolve_api_key(candidate.api_key_env or "")
        try:
            engine = create_engine(
                provider=candidate.provider,
                model=candidate.model,
                base_url=candidate.base_url,
                api_key=api_key,
            )
        except Exception as exc:
            print(f"  [SKIP] Engine creation failed: {exc}")
            continue

        if not await engine.ping():
            print(f"  [SKIP] Engine not reachable at {candidate.base_url}")
            await engine.close()
            continue

        results = await run_benchmark_suite(engine, cases)
        all_results[label] = results
        _write_jsonl(results, jsonl_path)
        await engine.close()

        for r in results:
            status = "PASS" if r.success else "FAIL"
            print(f"  [{status}] {r.case_id}: {r.ttft_ms:.0f}ms TTFT, {r.tok_per_sec:.1f} tok/s")

    if all_results:
        _write_markdown(all_results, md_path)
        print(f"\nResults: {jsonl_path}")
        print(f"Summary: {md_path}")
    else:
        print("\nNo engines were reachable. No results generated.")


if __name__ == "__main__":
    asyncio.run(main())
