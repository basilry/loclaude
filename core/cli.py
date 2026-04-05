#!/usr/bin/env python3
"""
local-claude CLI — rich + prompt_toolkit 기반 TUI.
claude-code의 main.tsx + claw-code의 rusty-claude-cli 참고.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pathlib import Path
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter

from core.config import load_config
from core.engine import MLXEngine
from core.runtime import ConversationRuntime
from core.session import Session, auto_title
from core.hooks import HookRunner
from core.tool_registry import ToolRegistry
from core.types import EventType, PermissionMode
from commands import CommandRegistry
from commands.builtins import register as register_builtins
from skills import file_ops, bash_exec, search, web_fetch

# ── 테마 ──

THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "thinking": "dim italic",
    "tool": "magenta",
    "prompt": "bold blue",
})

console = Console(theme=THEME)


# ── 초기화 ──

def build_tool_registry(workspace: str) -> ToolRegistry:
    registry = ToolRegistry()
    file_ops.register(registry, workspace)
    bash_exec.register(registry, workspace)
    search.register(registry, workspace)
    web_fetch.register(registry)
    return registry


def build_command_registry(get_session, get_runtime) -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry, get_session=get_session, get_runtime=get_runtime)
    return registry


async def check_server(engine: MLXEngine) -> bool:
    """MLX LM Server 연결 및 모델 확인."""
    try:
        info = await engine.ping()
        console.print(f"[success]✓[/] MLX LM Server (models: {info.get('models', '?')})", highlight=False)
    except Exception:
        console.print("[error]✗ MLX LM Server에 연결할 수 없습니다.[/]")
        console.print("  [dim]mlx_lm.server --model mlx-community/Qwen3.5-27B-4bit 을 실행하세요.[/]")
        return False

    model = await engine.find_model()
    if model:
        engine.model = model
        console.print(f"[success]✓[/] Model: {model}", highlight=False)
        return True
    else:
        console.print("[error]✗ 모델을 찾을 수 없습니다.[/]")
        console.print(f"  [dim]mlx_lm.server --model {engine.model}[/]")
        return False


# ── 응답 렌더링 ──

async def render_stream(runtime: ConversationRuntime, user_input: str) -> None:
    """스트리밍 응답을 rich로 렌더링."""
    text_buffer = ""
    thinking_buffer = ""
    tool_outputs = []

    async for event in runtime.submit(user_input):
        if event.type == EventType.THINKING_DELTA:
            thinking_buffer += event.data
            # thinking은 실시간으로 보여주되 dim 처리
            console.print(event.data, style="thinking", end="", highlight=False)

        elif event.type == EventType.TEXT_DELTA:
            if thinking_buffer and not text_buffer:
                # thinking → text 전환 시 줄바꿈
                console.print()
            text_buffer += event.data
            console.print(event.data, end="", highlight=False)

        elif event.type == EventType.TOOL_USE:
            tc = event.data
            console.print()
            console.print(
                Panel(
                    f"[tool]{tc.name}[/]({', '.join(f'{k}={repr(v)[:50]}' for k, v in tc.args.items())})",
                    title="[tool]Tool Call[/]",
                    border_style="magenta",
                    expand=False,
                )
            )

        elif event.type == EventType.TOOL_RESULT:
            tr = event.data
            style = "success" if tr.success else "error"
            output_preview = tr.output[:500] + ("..." if len(tr.output) > 500 else "")
            console.print(
                Panel(
                    output_preview,
                    title=f"[{style}]{tr.name} → {'OK' if tr.success else 'ERROR'}[/]",
                    border_style="green" if tr.success else "red",
                    expand=False,
                )
            )

        elif event.type == EventType.MESSAGE_STOP:
            usage = event.data
            if usage and usage.tok_per_sec > 0:
                console.print()
                console.print(
                    f"[dim]{usage.eval_count} tokens · {usage.tok_per_sec:.1f} tok/s[/]",
                    highlight=False,
                )

        elif event.type == EventType.ERROR:
            console.print(f"\n[error]{event.data}[/]")

    if text_buffer or thinking_buffer:
        console.print()  # 최종 줄바꿈


# ── 메인 REPL ──

async def repl(args: argparse.Namespace) -> None:
    workspace = os.path.abspath(args.workspace or ".")
    console.print(
        Panel(
            "[bold]local-claude[/] -- Qwen3.5-27B + MLX\n"
            f"[dim]Workspace: {workspace}[/]",
            border_style="blue",
        )
    )

    # 엔진 초기화
    engine = MLXEngine(
        model=args.model or None,
        base_url=args.server_url,
    )

    if not await check_server(engine):
        await engine.close()
        return

    # .local-claude/ 설정 로드
    project_config = load_config(workspace)
    if project_config.claude_md:
        console.print("[success]✓[/] CLAUDE.md loaded", highlight=False)
    if project_config.skills:
        console.print(f"[success]✓[/] Skills: {', '.join(s.name for s in project_config.skills)}", highlight=False)
    if project_config.agents:
        console.print(f"[success]✓[/] Agents: {', '.join(a.name for a in project_config.agents)}", highlight=False)

    # 도구 & 런타임
    tools = build_tool_registry(workspace)
    hooks = HookRunner()
    session = Session(session_dir=Path(workspace) / ".local-claude" / "sessions")

    permission = PermissionMode(args.permission) if args.permission else PermissionMode.FULL_ACCESS

    runtime = ConversationRuntime(
        engine=engine,
        tools=tools,
        hooks=hooks,
        session=session,
        permission_mode=permission,
        project_config=project_config,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    # 명령어
    commands = build_command_registry(
        get_session=lambda: runtime.session,
        get_runtime=lambda: runtime,
    )

    # prompt_toolkit 세션
    history_path = Path(workspace) / ".local-claude" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    slash_names = [f"/{c.name}" for c in commands.list_commands()]
    completer = WordCompleter(slash_names, sentence=True)

    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    console.print("[dim]Type /help for commands, /exit to quit.[/]\n")

    # 원샷 모드
    if args.prompt:
        await render_stream(runtime, args.prompt)
        await engine.close()
        return

    # REPL 루프
    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: prompt_session.prompt("❯ "),
            )
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Slash command 처리
        if user_input.startswith("/"):
            parts = user_input[1:].split(None, 1)
            cmd_name = parts[0]
            cmd_args = parts[1] if len(parts) > 1 else ""
            result = await commands.execute(cmd_name, cmd_args)

            if result == "__EXIT__":
                break
            elif result == "__CLEAR__":
                session = Session(session_dir=Path(workspace) / ".local-claude" / "sessions")
                runtime.session = session
                console.print("[info]Conversation cleared.[/]")
                continue
            elif result.startswith("__RESUME__:"):
                sid = result.split(":", 1)[1]
                try:
                    session = Session.load(sid, Path(workspace) / ".local-claude" / "sessions")
                    runtime.session = session
                    console.print(f"[success]Resumed session {sid} ({len(session.messages)} messages)[/]")
                except FileNotFoundError:
                    console.print(f"[error]Session not found: {sid}[/]")
                continue
            else:
                console.print(result)
                continue

        # 일반 메시지 → 에이전트 루프
        await render_stream(runtime, user_input)

        # 첫 응답 후 세션 타이틀 자동 생성
        if not runtime.session.title:
            try:
                await auto_title(runtime.session, runtime.engine)
                if runtime.session.title:
                    console.print(f"[dim]Session: {runtime.session.title}[/]", highlight=False)
            except Exception:
                pass

    console.print("[dim]Goodbye.[/]")
    await engine.close()


# ── CLI 파서 ──

def main():
    parser = argparse.ArgumentParser(
        prog="local-claude",
        description="Local AI coding assistant powered by Qwen3.5-27B + MLX",
    )
    parser.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive)")
    parser.add_argument("-w", "--workspace", default=".", help="Working directory")
    parser.add_argument("-m", "--model", help="Ollama model name override")
    parser.add_argument("--server-url", default="http://localhost:8080", help="MLX LM Server URL")
    parser.add_argument(
        "--permission",
        choices=["read-only", "workspace-write", "full-access"],
        default="full-access",
        help="Permission mode",
    )
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=4096)

    args = parser.parse_args()
    asyncio.run(repl(args))


if __name__ == "__main__":
    main()
