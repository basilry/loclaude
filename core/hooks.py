"""Hook 시스템. claw-code의 PreToolUse/PostToolUse 패턴 참고."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


class HookPhase(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_MESSAGE = "pre_message"       # 사용자 메시지 전처리
    POST_MESSAGE = "post_message"     # 어시스턴트 응답 후처리
    ON_ERROR = "on_error"


@dataclass
class HookContext:
    """Hook에 전달되는 컨텍스트."""
    phase: HookPhase
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_output: str | None = None
    message: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class HookResult:
    """Hook 실행 결과."""
    allow: bool = True          # False면 실행 중단
    modified_args: dict | None = None  # tool args 수정
    modified_output: str | None = None  # tool output 수정
    feedback: str | None = None  # 추가 메시지


# Hook 함수 시그니처
HookFn = Callable[[HookContext], HookResult | Awaitable[HookResult]]


class SecurityHook:
    """파괴적 명령 차단 + 위험 패턴 감지."""

    BLOCKED_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"git\s+reset\s+--hard",
        r"git\s+push\s+--force",
        r"chmod\s+777",
        r">\s*/etc/",
        r"curl.*\|\s*sh",
    ]

    WARN_PATTERNS = [
        r"rm\s+-rf",
        r"git\s+checkout\s+\.",
        r"pip\s+install.*--break",
    ]

    @classmethod
    def check(cls, command: str) -> tuple[bool, str]:
        """Returns (allowed, reason). False = blocked."""
        for pattern in cls.BLOCKED_PATTERNS:
            if re.search(pattern, command):
                return False, f"Blocked: matches dangerous pattern '{pattern}'"
        for pattern in cls.WARN_PATTERNS:
            if re.search(pattern, command):
                return True, f"Warning: matches risky pattern '{pattern}'"
        return True, ""


class HookRunner:
    """Hook 등록 및 실행."""

    def __init__(self):
        self._hooks: dict[HookPhase, list[HookFn]] = {phase: [] for phase in HookPhase}

    def register(self, phase: HookPhase, fn: HookFn) -> None:
        self._hooks[phase].append(fn)

    def on(self, phase: HookPhase):
        """데코레이터로 hook 등록."""
        def decorator(fn: HookFn):
            self.register(phase, fn)
            return fn
        return decorator

    async def run(self, ctx: HookContext) -> HookResult:
        """등록된 모든 hook 순차 실행. 하나라도 allow=False면 중단."""
        import asyncio
        import inspect

        result = HookResult()
        for fn in self._hooks.get(ctx.phase, []):
            if inspect.iscoroutinefunction(fn):
                r = await fn(ctx)
            else:
                r = fn(ctx)

            if r is None:
                continue
            if not r.allow:
                return r
            # 마지막 수정값을 사용
            if r.modified_args is not None:
                result.modified_args = r.modified_args
            if r.modified_output is not None:
                result.modified_output = r.modified_output
            if r.feedback:
                result.feedback = (result.feedback or "") + "\n" + r.feedback

        return result
