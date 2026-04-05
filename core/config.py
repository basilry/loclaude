"""
설정 로더 — .local-claude/ 디렉토리에서 CLAUDE.md, SKILL.md, agents/*.md 자동 발견.
claw-code의 ConfigLoader + claude-code의 assembleToolPool 패턴 참고.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillMeta:
    """SKILL.md 프론트매터 파싱 결과."""
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    path: Path | None = None
    content: str = ""  # 프론트매터 이후 본문


@dataclass
class AgentMeta:
    """agents/*.md 파싱 결과."""
    name: str
    role: str
    instructions: str
    tools: list[str] = field(default_factory=list)
    path: Path | None = None


@dataclass
class ProjectConfig:
    """프로젝트 전체 설정."""
    claude_md: str = ""                    # CLAUDE.md 내용
    skills: list[SkillMeta] = field(default_factory=list)
    agents: list[AgentMeta] = field(default_factory=list)
    config_dir: Path | None = None


def load_config(workspace: str = ".") -> ProjectConfig:
    """
    .local-claude/ 디렉토리에서 설정 자동 로드.

    구조:
      .local-claude/
        CLAUDE.md           → 시스템 프롬프트 주입
        skills/*/SKILL.md   → 스킬 메타데이터
        agents/*.md         → 에이전트 정의
    """
    ws = Path(workspace).resolve()
    config_dir = ws / ".local-claude"
    config = ProjectConfig(config_dir=config_dir)

    if not config_dir.exists():
        return config

    # 1. CLAUDE.md 로드
    claude_md = config_dir / "CLAUDE.md"
    if claude_md.exists():
        config.claude_md = claude_md.read_text(encoding="utf-8")

    # 2. Skills 발견
    skills_dir = config_dir / "skills"
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                meta = _parse_skill_md(skill_md)
                if meta:
                    config.skills.append(meta)

    # 3. Agents 발견
    agents_dir = config_dir / "agents"
    if agents_dir.exists():
        for agent_md in sorted(agents_dir.glob("*.md")):
            meta = _parse_agent_md(agent_md)
            if meta:
                config.agents.append(meta)

    return config


def build_system_prompt_from_config(config: ProjectConfig, tools_text: str = "") -> str:
    """ProjectConfig로부터 전체 시스템 프롬프트 조립."""
    parts = []

    # 기본 프롬프트
    parts.append(BASE_SYSTEM_PROMPT)

    # CLAUDE.md 주입
    if config.claude_md:
        parts.append("## User Instructions (CLAUDE.md)\n")
        parts.append(config.claude_md)

    # 스킬 요약 주입
    if config.skills:
        parts.append("## Available Skills\n")
        for skill in config.skills:
            parts.append(f"- **{skill.name}**: {skill.description}")
        parts.append("")

    # 에이전트 요약 주입
    if config.agents:
        parts.append("## Available Agents\n")
        for agent in config.agents:
            parts.append(f"- **{agent.name}** ({agent.role}): {agent.instructions[:100]}...")
        parts.append("")

    # 도구 목록
    if tools_text:
        parts.append(tools_text)

    return "\n\n".join(parts)


# ── 파서 ──

def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """--- ... --- YAML 프론트매터 파싱. pyyaml 없이도 간단한 key: value 지원."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not match:
        return {}, text

    fm_text, body = match.group(1), match.group(2)
    meta: dict[str, Any] = {}

    for line in fm_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # list 처리 (YAML inline list)
            if value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",")]
                meta[key] = [i for i in items if i]
            else:
                meta[key] = value

    # multi-line list 처리 (  - item 형태)
    current_key = None
    for line in fm_text.strip().split("\n"):
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("-"):
            key = stripped.split(":")[0].strip()
            value_part = stripped.split(":", 1)[1].strip()
            if not value_part:
                current_key = key
                if key not in meta:
                    meta[key] = []
            else:
                current_key = None
        elif stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip('"').strip("'")
            if not isinstance(meta.get(current_key), list):
                meta[current_key] = []
            meta[current_key].append(item)

    return meta, body


def _parse_skill_md(path: Path) -> SkillMeta | None:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    name = meta.get("name", path.parent.name)
    if not name:
        return None

    # triggers를 description에서 추출
    desc = meta.get("description", "")
    triggers = meta.get("triggers", [])
    if not triggers and "Triggers:" in desc:
        trigger_part = desc.split("Triggers:")[-1]
        triggers = [t.strip().strip("'.\"") for t in trigger_part.split(",")]

    tools = meta.get("tools", [])

    return SkillMeta(
        name=name,
        description=desc,
        tools=tools,
        triggers=triggers,
        path=path,
        content=body.strip(),
    )


def _parse_agent_md(path: Path) -> AgentMeta | None:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    name = meta.get("name", path.stem)
    role = meta.get("role", "assistant")
    tools = meta.get("tools", [])

    return AgentMeta(
        name=name,
        role=role,
        instructions=body.strip(),
        tools=tools,
        path=path,
    )


# ── 기본 시스템 프롬프트 ──

BASE_SYSTEM_PROMPT = """\
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

## Response Style
- Korean or English based on user's language
- Code blocks with language tags
- No unnecessary pleasantries
"""
