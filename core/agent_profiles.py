"""Agent Profile 로더. .local-claude/agents/*.md에서 프로필 파싱."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.config import _parse_frontmatter


@dataclass
class AgentProfile:
    name: str
    role: str
    system_prompt: str
    tools_allowed: list[str] = field(default_factory=list)
    source_path: Path | None = None


def load_agent_profile(path: Path) -> AgentProfile | None:
    """.md 파일에서 frontmatter + 본문을 파싱하여 AgentProfile 반환."""
    if not path.exists() or not path.suffix == ".md":
        return None

    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    name = meta.get("name", path.stem)
    if not name:
        return None

    return AgentProfile(
        name=name,
        role=meta.get("role", "assistant"),
        system_prompt=body.strip(),
        tools_allowed=meta.get("tools", []),
        source_path=path,
    )


def load_agent_profiles(agents_dir: Path) -> list[AgentProfile]:
    """디렉토리 내 모든 .md 파일에서 AgentProfile 로드."""
    if not agents_dir.exists():
        return []

    profiles: list[AgentProfile] = []
    for md_path in sorted(agents_dir.glob("*.md")):
        profile = load_agent_profile(md_path)
        if profile:
            profiles.append(profile)
    return profiles
