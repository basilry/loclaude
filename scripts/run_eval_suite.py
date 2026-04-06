#!/usr/bin/env python3
"""Eval suite CLI -- eval 케이스를 실행하고 결과를 JSONL + markdown으로 저장."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.engines.factory import create_engine
from core.evals import EvalCase, run_eval_suite, generate_eval_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run eval suite against an LLM engine")
    parser.add_argument(
        "--provider",
        default="openai-compat",
        help="Engine provider (default: openai-compat)",
    )
    parser.add_argument(
        "--model",
        default="llama3.2",
        help="Model name (default: llama3.2)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434/v1",
        help="Base URL for the engine API",
    )
    parser.add_argument(
        "--suite",
        required=True,
        help="Path to eval cases JSON file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory for results (default: eval_results/)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    # eval 케이스 로드
    suite_path = Path(args.suite)
    if not suite_path.exists():
        logger.error("Suite file not found: %s", suite_path)
        return 1

    cases = EvalCase.load_suite(suite_path)
    logger.info("Loaded %d eval cases from %s", len(cases), suite_path)

    # 엔진 생성
    engine = create_engine(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
    )

    # 실행
    try:
        results = await run_eval_suite(engine, cases)
    finally:
        await engine.close()

    # 출력 디렉토리 설정
    output_dir = Path(args.output) if args.output else Path("eval_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSONL 저장
    jsonl_path = output_dir / "results.jsonl"
    with open(jsonl_path, "w") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    logger.info("JSONL results saved to %s", jsonl_path)

    # Markdown 리포트 저장
    report = generate_eval_report(results)
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Markdown report saved to %s", report_path)

    # 결과 요약
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    logger.info("Results: %d passed, %d failed out of %d", passed, failed, len(results))

    print(report)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
