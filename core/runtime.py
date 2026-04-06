"""
ConversationRuntime — 에이전트 루프의 핵심.
claw-code의 ConversationRuntime + claude-code의 QueryEngine 패턴 결합.

턴 구조:
  1. 사용자 메시지 수신
  2. 시스템 프롬프트 + 히스토리 조립
  3. LLM 호출 (스트리밍)
  4. Tool call 감지 → 실행 → 결과 피드백
  5. Tool call이 없을 때까지 반복
  6. 세션 저장
"""

from __future__ import annotations

from typing import AsyncIterator, Callable, Awaitable

from core.config import ProjectConfig, build_system_prompt_from_config, load_config
from core.engines import EngineProtocol
from core.hooks import HookRunner, HookPhase, HookContext, HookResult
from core.project_paths import get_project_paths
from core.session import Session
from core.tool_registry import ToolRegistry
from core.types import (
    EventType, Message, PermissionMode, Role,
    StreamEvent, ToolCall, ToolResult, TokenUsage,
)


MAX_TOOL_OUTPUT = 8000  # characters — 도구 결과 truncation 임계값


class ConversationRuntime:
    """에이전트 대화 런타임. claw-code의 ConversationRuntime 역할."""

    def __init__(
        self,
        engine: EngineProtocol,
        tools: ToolRegistry,
        hooks: HookRunner | None = None,
        session: Session | None = None,
        permission_mode: PermissionMode = PermissionMode.FULL_ACCESS,
        system_prompt: str | None = None,
        project_config: ProjectConfig | None = None,
        max_iterations: int = 25,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        self.engine = engine
        self.tools = tools
        self.hooks = hooks or HookRunner()
        self.session = session or Session()
        self.permission_mode = permission_mode
        self.project_config = project_config
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 시스템 프롬프트 조립 — .local-claude/CLAUDE.md + SKILL.md 자동 로드
        self._system_prompt = self._build_system_prompt(system_prompt)

    def _build_system_prompt(self, custom: str | None) -> str:
        tools_text = self.tools.build_system_prompt_tools(self.permission_mode)

        if self.project_config:
            # .local-claude/ 설정 기반 프롬프트 조립
            prompt = build_system_prompt_from_config(self.project_config, tools_text)
            if custom:
                prompt += "\n\n" + custom
            return prompt

        # fallback: 기본 프롬프트
        parts = [SYSTEM_PROMPT_BASE]
        if custom:
            parts.append(custom)
        parts.append(tools_text)
        return "\n\n".join(parts)

    def _get_wiki_context(self, user_input: str) -> str:
        """사용자 메시지로 메모리 백엔드 검색, 관련 문서 snippet을 반환."""
        try:
            from core.memory import create_memory_backend

            wiki_dir = get_project_paths().wiki_dir
            stub_path = wiki_dir / "memory.json"
            if not stub_path.exists():
                return ""

            backend = create_memory_backend(wiki_dir=wiki_dir)

            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    results = pool.submit(
                        asyncio.run, backend.search(user_input, top_k=3)
                    ).result()
            else:
                results = asyncio.run(backend.search(user_input, top_k=3))

            if not results:
                return ""

            relevant = [r for r in results if r.get("score", 0) > 0.5]
            if not relevant:
                return ""

            snippets = []
            for r in relevant:
                title = r.get("title", "")
                snippet = r.get("snippet", "")[:300]
                path = r.get("wiki_path", "")
                source = f" (source: {path})" if path else ""
                snippets.append(f"- **{title}**{source}: {snippet}")

            return "\n\n## 관련 지식 베이스 문서\n" + "\n".join(snippets)
        except Exception:
            return ""

    # ── 메인 턴 실행 (스트리밍) ──

    async def submit(self, user_input: str) -> AsyncIterator[StreamEvent]:
        """사용자 메시지를 받아 에이전트 루프 실행. StreamEvent를 yield."""

        # 1. 사용자 메시지 추가
        user_msg = Message(role=Role.USER, content=user_input)
        self.session.add(user_msg)

        # 1.5. Wiki context injection
        wiki_context = self._get_wiki_context(user_input)
        active_system = self._system_prompt + wiki_context if wiki_context else self._system_prompt

        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1

            # 2. LLM 호출
            context = self.session.get_context()
            full_text = ""
            thinking_text = ""
            tool_calls: list[ToolCall] = []
            usage = TokenUsage()

            async for event in self.engine.chat_stream(
                context,
                system=active_system,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ):
                yield event

                if event.type == EventType.TEXT_DELTA:
                    full_text += event.data
                elif event.type == EventType.THINKING_DELTA:
                    thinking_text += event.data
                elif event.type == EventType.TOOL_USE:
                    tool_calls.append(event.data)
                elif event.type == EventType.MESSAGE_STOP:
                    usage = event.data

            # 3. 어시스턴트 메시지 저장
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=full_text,
                thinking=thinking_text or None,
                tool_calls=tool_calls or None,
            )
            self.session.add(assistant_msg)
            self.session.add_usage(usage)

            # 4. Tool call이 없으면 턴 종료
            if not tool_calls:
                return

            # 5. Tool call 실행
            for tc in tool_calls:
                # Pre-hook
                pre_ctx = HookContext(
                    phase=HookPhase.PRE_TOOL_USE,
                    tool_name=tc.name,
                    tool_args=tc.args,
                )
                pre_result = await self.hooks.run(pre_ctx)
                if not pre_result.allow:
                    tr = ToolResult(
                        tool_call_id=tc.id, name=tc.name,
                        output=pre_result.feedback or "Tool use denied by hook.",
                        success=False,
                    )
                else:
                    # 실제 실행
                    if pre_result.modified_args:
                        tc.args = pre_result.modified_args
                    tr = await self.tools.execute(tc)

                # Post-hook
                post_ctx = HookContext(
                    phase=HookPhase.POST_TOOL_USE,
                    tool_name=tc.name,
                    tool_args=tc.args,
                    tool_output=tr.output,
                )
                post_result = await self.hooks.run(post_ctx)
                if post_result.modified_output:
                    tr.output = post_result.modified_output

                # Truncation: 도구 결과가 너무 길면 자른다
                if tr.output and len(tr.output) > MAX_TOOL_OUTPUT:
                    original_len = len(tr.output)
                    tr.output = (
                        tr.output[:MAX_TOOL_OUTPUT]
                        + f"\n\n[... 출력이 {original_len}자로 잘렸습니다. "
                        + "전체 내용이 필요하면 read_file로 직접 확인하세요.]"
                    )

                # tool result를 세션에 추가
                yield StreamEvent(type=EventType.TOOL_RESULT, data=tr)
                tool_msg = Message(
                    role=Role.TOOL,
                    content=tr.output if tr.success else f"Error: {tr.error}",
                    name=tc.name,
                    tool_call_id=tc.id,
                )
                self.session.add(tool_msg)

            # 루프 계속 — LLM이 tool result를 보고 다음 응답 생성

        # max_iterations 도달
        yield StreamEvent(
            type=EventType.ERROR,
            data="Max iterations reached. Stopping agent loop.",
        )

    # ── Non-streaming 편의 메서드 ──

    async def ask(self, user_input: str) -> str:
        """전체 응답을 문자열로 반환 (non-streaming)."""
        parts = []
        async for event in self.submit(user_input):
            if event.type == EventType.TEXT_DELTA:
                parts.append(event.data)
        return "".join(parts)


# ── 시스템 프롬프트 ──

SYSTEM_PROMPT_BASE = """\
You are a local AI coding assistant, similar to Claude Code.
You help users with coding tasks by reading files, writing code, executing commands, and searching codebases.

## Behavior
- Be concise and direct
- Show code first, explain only when non-obvious
- When you need to use a tool, output a JSON tool call block
- After receiving tool results, continue your response
- Think step by step for complex tasks

## Tool Usage
When you need to perform an action, respond with exactly one JSON code block:
```json
{"tool": "tool_name", "args": {"param1": "value1"}}
```

Important rules:
- Use EXACTLY ONE tool call per response
- Wait for the tool result before making another call
- After all tool calls are done, provide your final answer
- If a tool returns an error, explain what went wrong and suggest fixes

## Tool Usage Priority
1. read_file, write_file, edit_file -- 파일 조작은 항상 네이티브 도구 우선
2. grep, glob -- 코드 검색은 전용 도구 사용 (bash grep/find 금지)
3. bash -- 시스템 명령, 빌드, 테스트 실행 시에만 사용
4. 복잡한 탐색이 필요하면 단계를 나누어 여러 도구 호출로 수행

## Important Rules
- read_file로 파일을 먼저 읽은 뒤에만 edit_file 사용
- 존재하지 않는 파일에 edit_file 사용 금지
- bash에서 rm -rf, git reset --hard 같은 파괴적 명령 금지

## Response Style
- Korean or English based on user's language
- Code blocks with language tags
- No unnecessary pleasantries
"""
