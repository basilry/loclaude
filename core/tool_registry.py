"""도구 레지스트리. claude-code의 assembleToolPool + claw-code의 ToolExecutor 참고."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from core.types import PermissionMode, ToolCall, ToolResult


@dataclass
class ToolSpec:
    """도구 정의."""
    name: str
    description: str
    parameters: dict  # JSON Schema
    fn: Callable[..., Any | Awaitable[Any]]
    is_async: bool = False
    permission_level: PermissionMode = PermissionMode.READ_ONLY

    def to_prompt_entry(self) -> str:
        """시스템 프롬프트용 도구 설명."""
        params = json.dumps(self.parameters.get("properties", {}), ensure_ascii=False)
        required = self.parameters.get("required", [])
        return (
            f"- **{self.name}**: {self.description}\n"
            f"  Parameters: {params}\n"
            f"  Required: {required}"
        )


class ToolRegistry:
    """도구 등록/조회/실행. claw-code의 GlobalToolRegistry 역할."""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        fn: Callable,
        permission_level: PermissionMode = PermissionMode.READ_ONLY,
    ) -> ToolSpec:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            fn=fn,
            is_async=inspect.iscoroutinefunction(fn),
            permission_level=permission_level,
        )
        self._tools[name] = spec
        return spec

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict,
        permission_level: PermissionMode = PermissionMode.READ_ONLY,
    ):
        """데코레이터."""
        def decorator(fn: Callable):
            self.register(name, description, parameters, fn, permission_level)
            return fn
        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def filter_by_permission(self, mode: PermissionMode) -> list[ToolSpec]:
        """허용된 permission 수준 이하의 도구만 반환."""
        levels = {
            PermissionMode.READ_ONLY: 0,
            PermissionMode.WORKSPACE_WRITE: 1,
            PermissionMode.FULL_ACCESS: 2,
        }
        max_level = levels[mode]
        return [t for t in self._tools.values() if levels[t.permission_level] <= max_level]

    def build_system_prompt_tools(self, mode: PermissionMode | None = None) -> str:
        """시스템 프롬프트에 삽입할 도구 목록."""
        tools = self.filter_by_permission(mode) if mode else self.list_tools()
        if not tools:
            return "No tools available."
        lines = ["## Available Tools", ""]
        lines.append(
            "When you need to use a tool, respond with a JSON block:\n"
            '```json\n{"tool": "tool_name", "args": {"key": "value"}}\n```\n'
        )
        for t in tools:
            lines.append(t.to_prompt_entry())
            lines.append("")
        return "\n".join(lines)

    async def execute(self, call: ToolCall) -> ToolResult:
        """도구 실행."""
        spec = self._tools.get(call.name)
        if not spec:
            return ToolResult(
                tool_call_id=call.id, name=call.name,
                output=f"Unknown tool: {call.name}", success=False,
                error=f"Tool '{call.name}' not found",
            )
        try:
            if spec.is_async:
                result = await spec.fn(**call.args)
            else:
                result = spec.fn(**call.args)

            output = result.get("output", str(result)) if isinstance(result, dict) else str(result)
            return ToolResult(
                tool_call_id=call.id, name=call.name,
                output=output, success=True,
            )
        except Exception as e:
            return ToolResult(
                tool_call_id=call.id, name=call.name,
                output="", success=False,
                error=f"{type(e).__name__}: {e}",
            )
