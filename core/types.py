"""핵심 타입 정의. claw-code의 AssistantEvent + claude-code의 Message 구조 참고."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── 메시지 ──

class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    DEVELOPER = "developer"


@dataclass
class Message:
    role: Role
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None   # tool result일 때
    name: str | None = None           # tool 이름
    thinking: str | None = None       # <think> 내용
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_openai(self) -> dict:
        """OpenAI 호환 API 호출용 dict (MLX, vLLM 등)."""
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d

    def to_jsonl(self) -> dict:
        """JSONL 세션 저장용."""
        d = {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.thinking:
            d["thinking"] = self.thinking
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


# ── Tool Call ──

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "args": self.args}

    @classmethod
    def from_dict(cls, d: dict) -> ToolCall:
        return cls(
            id=d.get("id", uuid.uuid4().hex[:8]),
            name=d.get("name") or d.get("tool", ""),
            args=d.get("args") or d.get("input", {}),
        )


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    output: str
    success: bool = True
    error: str | None = None


# ── 스트리밍 이벤트 (claw-code의 AssistantEvent 참고) ──

class EventType(str, Enum):
    TEXT_DELTA = "text_delta"
    THINKING_DELTA = "thinking_delta"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    MESSAGE_STOP = "message_stop"
    ERROR = "error"


@dataclass
class StreamEvent:
    type: EventType
    data: Any = None  # str for deltas, ToolCall for tool_use, etc.


# ── 토큰 사용량 ──

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    eval_count: int = 0
    eval_duration_ns: int = 0

    @property
    def tok_per_sec(self) -> float:
        if self.eval_duration_ns > 0:
            return self.eval_count / (self.eval_duration_ns / 1e9)
        return 0.0


# ── Permission ──

class PermissionMode(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL_ACCESS = "full-access"
