"""Slash command 레지스트리. claude-code의 commands.ts 패턴 참고."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Awaitable, Any


@dataclass
class Command:
    name: str
    description: str
    fn: Callable[..., str | Awaitable[str]]


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, name: str, description: str, fn: Callable) -> None:
        self._commands[name] = Command(name=name, description=description, fn=fn)

    def command(self, name: str, description: str):
        def decorator(fn):
            self.register(name, description, fn)
            return fn
        return decorator

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def list_commands(self) -> list[Command]:
        return list(self._commands.values())

    async def execute(self, name: str, args: str = "", **ctx) -> str:
        cmd = self._commands.get(name)
        if not cmd:
            return f"Unknown command: /{name}"
        import inspect
        if inspect.iscoroutinefunction(cmd.fn):
            return await cmd.fn(args, **ctx)
        return cmd.fn(args, **ctx)
