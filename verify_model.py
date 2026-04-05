#!/usr/bin/env python3
"""MLX 모델 검증 스크립트."""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.engine import MLXEngine
from core.types import EventType, Message, Role


async def main():
    print("=" * 55)
    print(" MLX LM Server -- Qwen3.5-27B-4bit 검증")
    print("=" * 55)

    engine = MLXEngine()

    # 1. 서버 연결
    print("\n1. Server connection...")
    try:
        info = await engine.ping()
        print(f"   OK: {info}")
    except Exception as e:
        print(f"   FAIL: {e}")
        print("   -> mlx_lm.server --model mlx-community/Qwen3.5-27B-4bit --port 8080")
        return 1

    # 2. 모델 탐색
    print("2. Model discovery...")
    model = await engine.find_model()
    if model:
        engine.model = model
        print(f"   OK: {model}")
    else:
        print(f"   FAIL: no compatible model found")
        return 1

    results = {}

    # 3. 기본 생성
    print("3. Basic generation...")
    content, thinking, tools, usage = await engine.chat(
        [Message(role=Role.USER, content="Say hello in one sentence.")],
        max_tokens=100,
    )
    print(f"   OK: {content[:100]}")
    results["basic"] = bool(content.strip())

    # 4. CoT 추론 (<think> 태그)
    print("4. Chain-of-thought...")
    content2, thinking2, _, _ = await engine.chat(
        [Message(role=Role.USER, content="What is 17 * 23? Think step by step.")],
        max_tokens=500,
    )
    has_thinking = thinking2 is not None and len(thinking2) > 0
    print(f"   OK: thinking={'yes' if has_thinking else 'no'}, answer={content2[:50]}")
    results["reasoning"] = has_thinking or bool(content2.strip())

    # 5. 스트리밍 속도
    print("5. Streaming speed...")
    start = time.monotonic()
    token_count = 0
    async for event in engine.chat_stream(
        [Message(role=Role.USER, content="Write a haiku about coding.")],
        max_tokens=100,
    ):
        if event.type == EventType.TEXT_DELTA:
            token_count += 1
    elapsed = time.monotonic() - start
    speed = token_count / elapsed if elapsed > 0 else 0
    print(f"   OK: {token_count} tokens in {elapsed:.1f}s ({speed:.1f} tok/s)")
    results["streaming"] = token_count > 0

    await engine.close()

    # 결과 요약
    print("\n" + "=" * 55)
    all_pass = all(results.values())
    for name, passed in results.items():
        print(f"  {name:<12} {'PASS' if passed else 'FAIL'}")
    print("=" * 55)

    if all_pass:
        print("\nAll checks passed! python -m core.cli 로 시작하세요.")
    else:
        print("\nSome checks failed. 모델/서버 설정을 확인하세요.")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
