"""셸 명령 실행 도구."""

from __future__ import annotations

import asyncio
import os

from core.hooks import SecurityHook
from core.tool_registry import ToolRegistry
from core.types import PermissionMode


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="bash",
        description="Execute a shell command. Returns stdout+stderr. Timeout: 120s.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command"},
                "timeout": {"type": "integer", "description": "Timeout seconds", "default": 120},
            },
            "required": ["command"],
        },
        permission_level=PermissionMode.FULL_ACCESS,
    )
    async def bash(command: str, timeout: int = 120) -> dict:
        allowed, reason = SecurityHook.check(command)
        if not allowed:
            return {"output": reason}
        if reason:  # warning
            pass  # logged but not blocked
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env={**os.environ, "TERM": "dumb"},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")

            result = out
            if err:
                result += f"\n[stderr]\n{err}"
            if proc.returncode and proc.returncode != 0:
                result += f"\n[exit code: {proc.returncode}]"
            if len(result) > 10000:
                result = result[:5000] + "\n...(truncated)...\n" + result[-3000:]
            return {"output": result.strip() or "(no output)"}
        except asyncio.TimeoutError:
            return {"output": f"Timed out after {timeout}s"}
        except Exception as e:
            return {"output": f"Error: {e}"}
