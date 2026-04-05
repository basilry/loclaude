"""파일 읽기/쓰기/편집 도구."""

from __future__ import annotations

from pathlib import Path

from core.tool_registry import ToolRegistry
from core.types import PermissionMode


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="read_file",
        description="Read file contents with line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "Start line (1-based)", "default": 1},
                "limit": {"type": "integer", "description": "Max lines", "default": 200},
            },
            "required": ["path"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def read_file(path: str, offset: int = 1, limit: int = 200) -> dict:
        p = _resolve(path, workspace)
        if not p.exists():
            return {"output": f"File not found: {path}"}
        if p.is_dir():
            return {"output": f"Path is a directory. Use list_files instead."}
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = max(0, offset - 1)
        selected = lines[start : start + limit]
        numbered = [f"{i + start + 1:>4} | {line}" for i, line in enumerate(selected)]
        header = f"[{p.name}] lines {start+1}-{min(start+limit, total)} of {total}"
        return {"output": header + "\n" + "\n".join(numbered)}

    @registry.tool(
        name="write_file",
        description="Write content to a file (creates parent dirs).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
        permission_level=PermissionMode.WORKSPACE_WRITE,
    )
    def write_file(path: str, content: str) -> dict:
        p = _resolve(path, workspace)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"output": f"Wrote {content.count(chr(10)) + 1} lines to {path}"}

    @registry.tool(
        name="edit_file",
        description="Replace exact string in a file. old_string must be unique.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to find"},
                "new_string": {"type": "string", "description": "Replacement"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        permission_level=PermissionMode.WORKSPACE_WRITE,
    )
    def edit_file(path: str, old_string: str, new_string: str) -> dict:
        p = _resolve(path, workspace)
        if not p.exists():
            return {"output": f"File not found: {path}"}
        text = p.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return {"output": "old_string not found in file."}
        if count > 1:
            return {"output": f"old_string has {count} matches — provide more context to make it unique."}
        p.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
        return {"output": f"Edited {path} (1 replacement)"}

    @registry.tool(
        name="list_files",
        description="List directory contents.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
                "recursive": {"type": "boolean", "default": False},
            },
            "required": [],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def list_files(path: str = ".", recursive: bool = False) -> dict:
        p = _resolve(path, workspace)
        if not p.is_dir():
            return {"output": f"Not a directory: {path}"}
        if recursive:
            entries = sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
        else:
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            entries = [f"{'[dir]  ' if f.is_dir() else '       '}{f.name}" for f in items]
        return {"output": "\n".join(entries[:300]) or "(empty directory)"}


def _resolve(path: str, workspace: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(workspace).resolve() / p
