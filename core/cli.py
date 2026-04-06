#!/usr/bin/env python3
"""
local-claude CLI -- rich + prompt_toolkit 기반 TUI.
claude-code의 main.tsx + claw-code의 rusty-claude-cli 참고.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter

from core.engines.base import EngineProtocol
from core.runtime import ConversationRuntime
from core.runtime_bootstrap import build_runtime_bundle, RuntimeBundle
from core.session import Session, auto_title
from core.types import EventType, PermissionMode

# -- 테마 --

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


# -- 헬스 체크 (provider-neutral) --

async def check_server(engine: EngineProtocol) -> bool:
    """Engine 연결 확인. provider에 독립적."""
    provider = getattr(engine, "provider_name", "unknown")
    try:
        ok = await engine.ping()
        if not ok:
            console.print(f"[error]x {provider} engine not reachable.[/]")
            return False
        console.print(f"[success]v[/] {provider} engine connected (model: {engine.model})", highlight=False)
    except Exception:
        console.print(f"[error]x {provider} engine not reachable.[/]")
        return False

    # MLX-specific: find_model
    if hasattr(engine, "find_model"):
        model = await engine.find_model()
        if model:
            engine.model = model
            console.print(f"[success]v[/] Model: {model}", highlight=False)
        else:
            console.print(f"[error]x Could not find model on server.[/]")
            console.print(f"  [dim]Expected: {engine.model}[/]")
            return False

    return True


# -- 응답 렌더링 --

async def render_stream(runtime: ConversationRuntime, user_input: str) -> None:
    """스트리밍 응답을 rich로 렌더링."""
    text_buffer = ""
    thinking_buffer = ""

    async for event in runtime.submit(user_input):
        if event.type == EventType.THINKING_DELTA:
            thinking_buffer += event.data
            console.print(event.data, style="thinking", end="", highlight=False)

        elif event.type == EventType.TEXT_DELTA:
            if thinking_buffer and not text_buffer:
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
                    title=f"[{style}]{tr.name} -> {'OK' if tr.success else 'ERROR'}[/]",
                    border_style="green" if tr.success else "red",
                    expand=False,
                )
            )

        elif event.type == EventType.MESSAGE_STOP:
            usage = event.data
            if usage and usage.tok_per_sec > 0:
                console.print()
                console.print(
                    f"[dim]{usage.eval_count} tokens - {usage.tok_per_sec:.1f} tok/s[/]",
                    highlight=False,
                )

        elif event.type == EventType.ERROR:
            console.print(f"\n[error]{event.data}[/]")

    if text_buffer or thinking_buffer:
        console.print()


# -- 메인 REPL --

async def repl(args: argparse.Namespace) -> None:
    workspace = os.path.abspath(args.workspace or ".")
    console.print(
        Panel(
            f"[bold]local-claude[/] -- {getattr(args, 'provider', 'mlx')} provider\n"
            f"[dim]Workspace: {workspace}[/]",
            border_style="blue",
        )
    )

    bundle = build_runtime_bundle(args, workspace)

    if not await check_server(bundle.engine):
        await bundle.engine.close()
        return

    # .local-claude/ 설정 표시
    if bundle.project_config.claude_md:
        console.print("[success]v[/] CLAUDE.md loaded", highlight=False)
    if bundle.project_config.skills:
        console.print(f"[success]v[/] Skills: {', '.join(s.name for s in bundle.project_config.skills)}", highlight=False)
    if bundle.project_config.agents:
        console.print(f"[success]v[/] Agents: {', '.join(a.name for a in bundle.project_config.agents)}", highlight=False)

    # prompt_toolkit 세션
    history_path = Path(workspace) / ".local-claude" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    slash_names = [f"/{c.name}" for c in bundle.commands.list_commands()]
    completer = WordCompleter(slash_names, sentence=True)

    prompt_session: PromptSession = PromptSession(
        history=FileHistory(str(history_path)),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
    )

    console.print("[dim]Type /help for commands, /exit to quit.[/]\n")

    # 원샷 모드
    if args.prompt:
        await render_stream(bundle.runtime, args.prompt)
        await bundle.engine.close()
        return

    # REPL 루프
    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: prompt_session.prompt(">>> "),
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
            result = await bundle.commands.execute(cmd_name, cmd_args)

            if result == "__EXIT__":
                break
            elif result == "__CLEAR__":
                session = Session(session_dir=bundle.paths.sessions_dir)
                bundle.runtime.session = session
                console.print("[info]Conversation cleared.[/]")
                continue
            elif result.startswith("__RESUME__:"):
                sid = result.split(":", 1)[1]
                try:
                    session = Session.load(sid, bundle.paths.sessions_dir)
                    bundle.runtime.session = session
                    console.print(f"[success]Resumed session {sid} ({len(session.messages)} messages)[/]")
                except FileNotFoundError:
                    console.print(f"[error]Session not found: {sid}[/]")
                continue
            else:
                console.print(result)
                continue

        # 일반 메시지 -> 에이전트 루프
        await render_stream(bundle.runtime, user_input)

        # 첫 응답 후 세션 타이틀 자동 생성
        if not bundle.runtime.session.title:
            try:
                await auto_title(bundle.runtime.session, bundle.runtime.engine)
                if bundle.runtime.session.title:
                    console.print(f"[dim]Session: {bundle.runtime.session.title}[/]", highlight=False)
            except Exception:
                pass

    console.print("[dim]Goodbye.[/]")
    await bundle.engine.close()


# -- CLI 파서 --

def main():
    parser = argparse.ArgumentParser(
        prog="local-claude",
        description="Local AI coding assistant powered by local/remote LLM engines",
    )
    parser.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive)")
    parser.add_argument("-w", "--workspace", default=".", help="Working directory")
    parser.add_argument("-m", "--model", help="Model name override")
    parser.add_argument("--server-url", dest="base_url", default="http://localhost:8080/v1", help="LLM server URL")
    parser.add_argument("--provider", default="mlx", choices=["mlx", "openai", "openai-compat"], help="Engine provider")
    parser.add_argument("--base-url", default=None, help="Engine base URL (overrides --server-url)")
    parser.add_argument("--timeout", type=int, default=120, help="Request timeout in seconds")
    parser.add_argument("--api-key-env", default="", help="Environment variable name for API key")
    parser.add_argument(
        "--permission",
        choices=["read-only", "workspace-write", "full-access"],
        default="full-access",
        help="Permission mode",
    )
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=4096)

    args = parser.parse_args()

    # --base-url overrides --server-url
    if args.base_url is None:
        # base_url attr already set by --server-url dest
        pass

    asyncio.run(repl(args))


if __name__ == "__main__":
    main()
