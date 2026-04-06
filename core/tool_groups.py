"""도구 그룹 정의. 관련 도구를 논리적 그룹으로 묶어 관리."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolGroup:
    """A logical grouping of related tools."""
    name: str
    description: str
    tool_names: list[str] = field(default_factory=list)
    auto_load: bool = True


def build_default_tool_groups() -> list[ToolGroup]:
    """Return the default tool groups for local-claude."""
    return [
        ToolGroup(
            name="coding",
            description="파일 조작, Git, 테스트",
            tool_names=[
                "read_file", "write_file", "edit_file", "list_files",
                "bash",
                "git_status", "git_diff", "git_show",
                "run_pytest", "run_script", "list_test_targets",
            ],
        ),
        ToolGroup(
            name="knowledge",
            description="위키, 검색, 캡슐",
            tool_names=[
                "grep", "glob",
                "wiki_upsert", "wiki_search", "wiki_backlink_check",
            ],
        ),
        ToolGroup(
            name="web",
            description="웹 가져오기",
            tool_names=["web_fetch"],
        ),
    ]
